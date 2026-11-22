"""LyraForge command-line interface (M0 + M1-A/B library & preview).

Commands:
  lyraforge inspect <file.mid>
  lyraforge arrange <file.mid> [-o performance.json] [--report report.json] [options]
  lyraforge validate <performance.json>
  lyraforge playback dry-run <performance.json | arrangement_id> [--realtime] [--log actions.jsonl]
  lyraforge profiles list | show <id>
  lyraforge import <file.mid> [--title ...] [--artist ...] [--tags a,b]
  lyraforge library list | search <query> | show <song_id> | arrange <song_id> [options]
  lyraforge preview <performance.json | arrangement_id> [-o out.wav] [--sample-rate 22050]

There is intentionally NO command that sends real keyboard input in M0/M1-A/B.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lyraforge import __version__
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import DEFAULT_PROFILE_ID, list_profile_ids, load_builtin_profile
from lyraforge.library import (
    LibraryStore,
    atomic_write_bytes,
    atomic_write_text,
    export_backup_zip,
    export_lyrapack,
    import_lyrapack,
)
from lyraforge.music_core.arranger import ArrangeOptions, SemitonePolicy, Style, arrange
from lyraforge.music_core.canonical import pretty_json
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import (
    build_performance,
    build_report,
    validate_performance,
)
from lyraforge.playback import DryRunDriver, MonotonicClock, Player, StopToken, VirtualClock
from lyraforge.preview import DEFAULT_SAMPLE_RATE, synthesize_performance_to_wav

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PLAYBACK_INCOMPLETE = 4


def _emit(text: str, out: str | None) -> None:
    if out and out != "-":
        atomic_write_text(Path(out), text)
    else:
        sys.stdout.write(text)


def _load_json(path: str) -> Any:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"file not found: {p.name}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LyraError(ErrorCode.PERFORMANCE_INVALID, f"not valid JSON: {exc}") from exc


def _parse_transpose(value: str) -> int | None:
    if value == "auto":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("transpose must be 'auto' or an integer") from exc


def _parse_tracks(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in value.split(",") if x.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tracks must be a comma-separated list of ints") from exc


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


def _build_arrange_options(args: argparse.Namespace) -> ArrangeOptions:
    return ArrangeOptions(
        style=Style(args.style),
        transpose=args.transpose,
        semitone_policy=SemitonePolicy(args.semitone_policy),
        max_chord_keys=args.max_chord_keys,
        chord_window_ms=args.chord_window_ms,
        speed=args.speed,
        include_tracks=args.tracks,
        exclude_percussion=not args.include_percussion,
    )


def _add_arrange_option_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--instrument", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--style", choices=[s.value for s in Style], default=Style.BALANCED.value)
    parser.add_argument(
        "--transpose",
        type=_parse_transpose,
        default=None,
        help="'auto' (default) or semitones",
    )
    parser.add_argument(
        "--semitone-policy",
        choices=[s.value for s in SemitonePolicy],
        default=SemitonePolicy.NEAREST.value,
    )
    parser.add_argument("--max-chord-keys", type=int, default=None)
    parser.add_argument("--chord-window-ms", type=int, default=20)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--tracks", type=_parse_tracks, default=None, help="e.g. 0,2")
    parser.add_argument("--include-percussion", action="store_true")


def _validate_doc_with_builtin_profile(doc: Any) -> None:
    profile = None
    if isinstance(doc, dict) and doc.get("instrument_profile_id") in list_profile_ids():
        profile = load_builtin_profile(doc["instrument_profile_id"])
    validate_performance(doc, profile)


def cmd_inspect(args: argparse.Namespace) -> int:
    score = load_midi_file(args.midi)
    _emit(pretty_json(score.summary()), args.output)
    return EXIT_OK


def cmd_arrange(args: argparse.Namespace) -> int:
    profile = load_builtin_profile(args.instrument)
    score = load_midi_file(args.midi)
    opts = _build_arrange_options(args)
    arr = arrange(score, profile, opts)
    perf = build_performance(score, profile, arr)
    validate_performance(perf, profile)  # never emit an invalid document
    _emit(pretty_json(perf), args.output)
    if args.report:
        atomic_write_text(Path(args.report), pretty_json(build_report(score, profile, arr)))
    s = arr.stats
    print(
        f"arranged {s['emitted_events']}/{s['considered_notes']} notes "
        f"(transpose {arr.transpose:+d}, folded {s['octave_folded']}, "
        f"substituted {s['semitone_substituted']}, dropped {sum(s['dropped'].values())}) "
        f"-> {args.output or 'stdout'}",
        file=sys.stderr,
    )
    if profile.calibration_status != "verified":
        print(
            f"note: profile {profile.id} calibration is '{profile.calibration_status}'",
            file=sys.stderr,
        )
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    doc = _load_json(args.performance)
    profile = None
    if isinstance(doc, dict) and doc.get("instrument_profile_id") in list_profile_ids():
        profile = load_builtin_profile(doc["instrument_profile_id"])
    validate_performance(doc, profile)
    print(
        f"OK: {len(doc['events'])} events, profile {doc['instrument_profile_id']}"
        f"{' (hash verified)' if profile else ' (profile not built-in; hash not checked)'}"
    )
    return EXIT_OK


def cmd_dry_run(args: argparse.Namespace) -> int:
    target = args.performance
    arrangement_id: str | None = None
    if Path(target).is_file():
        doc = _load_json(target)
    else:
        with LibraryStore(args.data_dir) as store:
            try:
                doc = store.load_arrangement_performance(target)
                arrangement_id = target
            except LyraError as exc:
                if Path(target).suffix.lower() == ".json":
                    raise LyraError(
                        ErrorCode.SOURCE_UNAVAILABLE, f"file not found: {Path(target).name}"
                    ) from exc
                raise

    _validate_doc_with_builtin_profile(doc)
    base_clock = MonotonicClock() if args.realtime else VirtualClock()
    stop = StopToken()
    clock: Any = base_clock
    if args.stop_after_ms is not None:
        # Simulated user stop: the token fires once the offset is reached.
        clock = _StopAtClock(base_clock, stop, args.stop_after_ms * 1000)
    driver = DryRunDriver(clock)
    events = doc["events"]
    player = Player(driver, clock, stop_token=stop)
    try:
        result = player.play(events)
    except KeyboardInterrupt:
        print("interrupted; all keys released", file=sys.stderr)
        return EXIT_PLAYBACK_INCOMPLETE

    mode = "realtime" if args.realtime else "virtual"
    if arrangement_id is not None:
        with LibraryStore(args.data_dir) as store:
            store.record_playback_session(arrangement_id, f"dry-run:{mode}", result)

    t0 = result.started_at_us
    if args.log:
        lines = [
            json.dumps({"t_ms": round((e.t_us - t0) / 1000, 3), "action": e.action,
                        "key_id": e.key_id})
            for e in driver.log
        ]
        atomic_write_text(Path(args.log), "\n".join(lines) + ("\n" if lines else ""))
    summary = result.to_json()
    summary["mode"] = mode
    summary["sent_os_input"] = False
    summary["keys_still_pressed"] = sorted(driver.pressed)
    print(pretty_json(summary), end="")
    return EXIT_OK if result.state == "completed" else EXIT_PLAYBACK_INCOMPLETE


class _StopAtClock:
    """Clock wrapper that requests a stop once a time offset is reached (testing aid)."""

    def __init__(self, inner: Any, stop: StopToken, after_us: int):
        self._inner = inner
        self._stop = stop
        self._deadline = inner.now_us() + after_us

    def now_us(self) -> int:
        now = self._inner.now_us()
        if now >= self._deadline:
            self._stop.request_stop("simulated stop (--stop-after-ms)")
        return now

    def sleep_us(self, us: int) -> None:
        self._inner.sleep_us(us)


def cmd_profiles_list(_args: argparse.Namespace) -> int:
    for pid in list_profile_ids():
        p = load_builtin_profile(pid)
        print(
            f"{p.id}\t{p.display_name}\tkeys={len(p.keys)}\t"
            f"range={p.min_pitch}-{p.max_pitch}\tcalibration={p.calibration_status}"
        )
    return EXIT_OK


def cmd_profiles_show(args: argparse.Namespace) -> int:
    p = load_builtin_profile(args.profile_id)
    data = dict(p.raw)
    data["_hash"] = p.hash
    print(pretty_json(data), end="")
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    from lyraforge.media import SUPPORTED_MEDIA_EXTENSIONS

    ext = Path(args.midi).suffix.lower()
    with LibraryStore(args.data_dir) as store:
        if ext in SUPPORTED_MEDIA_EXTENSIONS:
            res = store.import_audio(
                args.midi,
                title=args.title,
                artist=args.artist,
                tags=_parse_tags(args.tags),
            )
        else:
            res = store.import_midi(
                args.midi,
                title=args.title,
                artist=args.artist,
                tags=_parse_tags(args.tags),
            )
    print(pretty_json(res.to_json()), end="")
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        data = store.export_arrangement(args.arrangement_id, args.format)
    out_path = Path(args.output)
    atomic_write_bytes(out_path, data)
    print(
        pretty_json(
            {
                "arrangement_id": args.arrangement_id,
                "format": args.format,
                "output": str(out_path),
                "size_bytes": len(data),
            }
        ),
        end="",
    )
    return EXIT_OK


def cmd_library_list(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        songs = [s.to_json() for s in store.search_songs("")]
    print(pretty_json(songs), end="")
    return EXIT_OK


def cmd_library_search(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        songs = [s.to_json() for s in store.search_songs(args.query)]
    print(pretty_json(songs), end="")
    return EXIT_OK


def cmd_library_show(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        detail = store.get_song(args.song_id)
    print(pretty_json(detail.to_json()), end="")
    return EXIT_OK


def cmd_library_arrange(args: argparse.Namespace) -> int:
    opts = _build_arrange_options(args)
    with LibraryStore(args.data_dir) as store:
        rec = store.arrange_song(args.song_id, profile_id=args.instrument, options=opts)
    print(pretty_json(rec.to_json()), end="")
    return EXIT_OK


def cmd_library_backup(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        data = export_backup_zip(store)
    out = Path(args.output)
    atomic_write_bytes(out, data)
    print(pretty_json({"output": str(out), "size_bytes": len(data)}), end="")
    return EXIT_OK


def cmd_pack_export(args: argparse.Namespace) -> int:
    with LibraryStore(args.data_dir) as store:
        data = export_lyrapack(
            store,
            args.arrangement_id,
            copyright_confirmed=bool(args.confirm_rights),
            license_notice=args.license_note,
        )
    out = Path(args.output)
    atomic_write_bytes(out, data)
    print(
        pretty_json(
            {
                "arrangement_id": args.arrangement_id,
                "output": str(out),
                "size_bytes": len(data),
                "includes_source_audio": False,
            }
        ),
        end="",
    )
    return EXIT_OK


def cmd_pack_import(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.is_file():
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"package not found: {src.name}")
    with LibraryStore(args.data_dir) as store:
        res = import_lyrapack(store, src.read_bytes())
    print(pretty_json(res), end="")
    return EXIT_OK


def cmd_preview(args: argparse.Namespace) -> int:
    target = args.target
    if Path(target).is_file():
        if not args.output:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "--output is required when previewing a performance JSON file directly",
            )
        doc = _load_json(target)
        out_path = synthesize_performance_to_wav(
            doc, args.output, sample_rate=args.sample_rate
        )
        payload: dict[str, Any] = {
            "source": target,
            "wav_path": str(out_path),
            "size_bytes": out_path.stat().st_size,
            "sample_rate": args.sample_rate,
        }
    else:
        with LibraryStore(args.data_dir) as store:
            wav_path = store.render_preview(target, sample_rate=args.sample_rate)
            out_path = wav_path
            if args.output:
                out_path = Path(args.output)
                atomic_write_bytes(out_path, wav_path.read_bytes())
        payload = {
            "arrangement_id": target,
            "wav_path": str(out_path),
            "size_bytes": out_path.stat().st_size,
            "sample_rate": args.sample_rate,
        }
    print(pretty_json(payload), end="")
    return EXIT_OK


def cmd_agent(args: argparse.Namespace) -> int:
    from lyraforge.agent import AgentOrchestrator

    with LibraryStore(args.data_dir) as store:
        orch = AgentOrchestrator(store)
        res = orch.run(
            args.prompt,
            song_id=args.song_id,
            arrangement_id=args.arrangement_id,
            allow_network=args.allow_network,
            local_path=args.file,
            source_url=args.url,
        )
    print(pretty_json(res.to_json()), end="")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "local API server may only bind to loopback (127.0.0.1 / localhost / ::1)",
            {"host": args.host},
        )
    import uvicorn

    from lyraforge.api import create_app
    from lyraforge.api.app import default_web_dist_dir

    app = create_app(
        data_dir=args.data_dir,
        session_token=args.token,
        cors_origins=args.cors_origin or (),
        static_dir=default_web_dist_dir(),
    )
    print(
        f"LyraForge local API listening on http://{args.host}:{args.port} "
        f"(session token configured)",
        file=sys.stderr,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return EXIT_OK


def cmd_desktop(args: argparse.Namespace) -> int:
    from lyraforge.desktop import launch_desktop

    return launch_desktop(
        data_dir=args.data_dir,
        static_dir=args.static_dir,
        dev_url=args.dev_url,
    )


def cmd_engines_list(_args: argparse.Namespace) -> int:
    from lyraforge.transcribers import list_transcribers

    print(pretty_json([m.to_json() for m in list_transcribers()]), end="")
    return EXIT_OK


def cmd_transcribe(args: argparse.Namespace) -> int:
    import tempfile

    from lyraforge.media import extract_audio_to_wav
    from lyraforge.music_core.cleanup import clean_score
    from lyraforge.music_core.midi_export import score_to_midi_bytes
    from lyraforge.music_core.midi_import import parse_midi_bytes
    from lyraforge.transcribers import TranscribeOptions, get_transcriber

    engine = get_transcriber(args.engine)
    opts = TranscribeOptions(
        min_pitch=args.min_pitch,
        max_pitch=args.max_pitch,
        min_note_ms=args.min_note_ms,
    )
    with tempfile.TemporaryDirectory(prefix="lyraforge-cli-tr-") as tmpdir:
        wav_path = Path(tmpdir) / "extracted.wav"
        extract_audio_to_wav(args.audio, wav_path)
        res = engine.transcribe(wav_path, options=opts)

    raw_score = parse_midi_bytes(res.midi_bytes)
    cleaned_score, clean_stats = clean_score(raw_score)
    cleaned_bytes = score_to_midi_bytes(cleaned_score)

    if args.output:
        atomic_write_bytes(Path(args.output), res.midi_bytes)
    if args.cleaned_out:
        atomic_write_bytes(Path(args.cleaned_out), cleaned_bytes)
    if args.arrange_out:
        profile = load_builtin_profile(args.instrument)
        arr = arrange(cleaned_score, profile, ArrangeOptions(style=Style(args.style)))
        perf = build_performance(cleaned_score, profile, arr)
        validate_performance(perf, profile)
        atomic_write_text(Path(args.arrange_out), pretty_json(perf))

    summary = {
        "engine_id": res.engine_id,
        "engine_version": res.engine_version,
        "raw_note_count": res.note_count,
        "cleaned_note_count": clean_stats["kept_notes"],
        "duration_ms": res.duration_ms,
        "raw_midi_out": args.output,
        "cleaned_midi_out": args.cleaned_out,
        "performance_out": args.arrange_out,
        "warnings": list(res.warnings),
    }
    print(pretty_json(summary), end="")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lyraforge", description="LyraForge CLI (offline)")
    ap.add_argument("--version", action="version", version=f"lyraforge {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="parse a MIDI file and print a normalized summary")
    p.add_argument("midi")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("arrange", help="MIDI -> performance.json for an instrument profile")
    p.add_argument("midi")
    p.add_argument("-o", "--output", help="performance.json path (default: stdout)")
    p.add_argument("--report", help="write arrangement report JSON here")
    _add_arrange_option_flags(p)
    p.set_defaults(func=cmd_arrange)

    p = sub.add_parser("validate", help="validate a performance.json")
    p.add_argument("performance")
    p.set_defaults(func=cmd_validate)

    pb = sub.add_parser("playback", help="playback (dry-run only, no OS input)")
    pbs = pb.add_subparsers(dest="playback_command", required=True)
    p = pbs.add_parser("dry-run", help="simulate playback; sends no keyboard input")
    p.add_argument("performance", help="path to performance.json or saved arrangement_id")
    p.add_argument("--realtime", action="store_true", help="wait in real time (monotonic clock)")
    p.add_argument("--log", help="write per-action JSONL log")
    p.add_argument(
        "--stop-after-ms",
        type=int,
        default=None,
        help="simulate a user stop at this offset (tests key release)",
    )
    p.add_argument("--data-dir", default=None, help="override LyraForge data directory")
    p.set_defaults(func=cmd_dry_run)

    pp = sub.add_parser("profiles", help="instrument profiles")
    pps = pp.add_subparsers(dest="profiles_command", required=True)
    p = pps.add_parser("list")
    p.set_defaults(func=cmd_profiles_list)
    p = pps.add_parser("show")
    p.add_argument("profile_id")
    p.set_defaults(func=cmd_profiles_show)

    pi = sub.add_parser("import", help="import a local MIDI or audio/video file into the library")
    pi.add_argument("midi", help="path to .mid/.midi or supported audio/video file")
    pi.add_argument("--title", default=None)
    pi.add_argument("--artist", default="")
    pi.add_argument("--tags", default=None, help="comma-separated tags")
    pi.add_argument("--data-dir", default=None, help="override LyraForge data directory")
    pi.set_defaults(func=cmd_import)

    px = sub.add_parser("export", help="export a saved arrangement as MIDI or JSON")
    px.add_argument("arrangement_id")
    px.add_argument("--format", choices=["midi", "json"], default="midi")
    px.add_argument("-o", "--output", required=True, help="output file path")
    px.add_argument("--data-dir", default=None)
    px.set_defaults(func=cmd_export)

    pl = sub.add_parser("library", help="query and arrange songs in the local library")
    pls = pl.add_subparsers(dest="library_command", required=True)
    p = pls.add_parser("list", help="list all songs in the library")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_library_list)

    p = pls.add_parser("search", help="search songs by title, artist, or tag")
    p.add_argument("query")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_library_search)

    p = pls.add_parser("show", help="show song sources and arrangements")
    p.add_argument("song_id")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_library_show)

    p = pls.add_parser("arrange", help="create/fetch an arrangement for an imported song")
    p.add_argument("song_id")
    _add_arrange_option_flags(p)
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_library_arrange)

    p = pls.add_parser("backup", help="export a full ZIP backup of the SQLite library")
    p.add_argument("-o", "--output", required=True, help="output backup.zip path")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_library_backup)

    pk = sub.add_parser("pack", help="export or import shareable .lyrapack archives")
    pks = pk.add_subparsers(dest="pack_command", required=True)
    p = pks.add_parser("export", help="export arrangement as .lyrapack (omits source audio)")
    p.add_argument("arrangement_id")
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--confirm-rights",
        action="store_true",
        help="confirm you have rights to share this arrangement",
    )
    p.add_argument("--license-note", default="")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_pack_export)

    p = pks.add_parser("import", help="safely validate and import a .lyrapack file")
    p.add_argument("file")
    p.add_argument("--data-dir", default=None)
    p.set_defaults(func=cmd_pack_import)

    pv = sub.add_parser("preview", help="synthesize an offline WAV preview")
    pv.add_argument("target", help="path to performance.json or saved arrangement_id")
    pv.add_argument("-o", "--output", default=None, help="output WAV path")
    pv.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    pv.add_argument("--data-dir", default=None)
    pv.set_defaults(func=cmd_preview)

    ps = sub.add_parser("serve", help="run the local loopback FastAPI server")
    ps.add_argument("--host", default="127.0.0.1", help="loopback host only (default: 127.0.0.1)")
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--data-dir", default=None)
    ps.add_argument("--token", default=None, help="optional fixed session token for dev")
    ps.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="allowed origin (repeatable)",
    )
    ps.set_defaults(func=cmd_serve)

    pd = sub.add_parser("desktop", help="launch the PyWebView desktop application")
    pd.add_argument("--data-dir", default=None)
    pd.add_argument("--static-dir", default=None, help="override built Vue frontend dist dir")
    pd.add_argument("--dev-url", default=None, help="Vite dev server URL for hot-reload dev")
    pd.set_defaults(func=cmd_desktop)

    pe = sub.add_parser("engines", help="audio-to-MIDI transcription engines")
    pes = pe.add_subparsers(dest="engines_command", required=True)
    p = pes.add_parser("list", help="list available transcription engines")
    p.set_defaults(func=cmd_engines_list)

    pt = sub.add_parser("transcribe", help="transcribe local audio/video into MIDI")
    pt.add_argument("audio")
    pt.add_argument("--engine", default="builtin-mono")
    pt.add_argument("-o", "--output", default=None, help="write raw.mid path")
    pt.add_argument("--cleaned-out", default=None, help="write cleaned.mid path")
    pt.add_argument("--arrange-out", default=None, help="also arrange into performance.json")
    pt.add_argument("--instrument", default=DEFAULT_PROFILE_ID)
    pt.add_argument("--style", choices=[s.value for s in Style], default=Style.BALANCED.value)
    pt.add_argument("--min-pitch", type=int, default=36)
    pt.add_argument("--max-pitch", type=int, default=96)
    pt.add_argument("--min-note-ms", type=int, default=60)
    pt.set_defaults(func=cmd_transcribe)

    pa = sub.add_parser("agent", help="run AI agent natural-language search and arrangement")
    pa.add_argument("prompt", help="natural-language request")
    pa.add_argument("--song-id", default=None)
    pa.add_argument("--arrangement-id", default=None)
    pa.add_argument("--file", default=None, help="explicit local MIDI/audio file path")
    pa.add_argument("--url", default=None, help="explicit user-authorized external URL")
    pa.add_argument("--allow-network", action="store_true")
    pa.add_argument("--data-dir", default=None)
    pa.set_defaults(func=cmd_agent)

    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows code pages
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except LyraError as err:
        print(f"error [{err.code}]: {err.message}", file=sys.stderr)
        for prob in err.details.get("problems", [])[:20]:
            print(f"  - {prob}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
