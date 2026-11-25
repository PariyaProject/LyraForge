"""Unit and integration tests for Plan A (vocal_dynamic / phrase DP / alignment / stem RMS)
and Plan B (fixed-velocity preview + CLI/API/MCP parity).
"""

from __future__ import annotations

import json
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import create_app
from lyraforge.api.app import SESSION_TOKEN_HEADER
from lyraforge.cli import main as cli_main
from lyraforge.instruments import load_builtin_profile
from lyraforge.library.store import LibraryStore
from lyraforge.mcp import LyraMCPServer, MCPTaskRegistry, MCPToolExecutor
from lyraforge.music_core import (
    AccompDensity,
    ArrangeOptions,
    NormalizedScore,
    Note,
    PhraseOctaveMode,
    StemDynamics,
    TempoChange,
    TempoMap,
    TrackInfo,
    align_accompaniment_onsets,
    arrange,
    optimize_phrase_octaves,
)
from lyraforge.music_core.arranger import DropReason, Style
from lyraforge.music_core.midi_export import score_to_midi_bytes
from lyraforge.music_core.performance import build_performance
from lyraforge.pipelines import PipelineRequest, get_pipeline
from lyraforge.preview import synthesize_performance
from lyraforge.separators import SeparatedStems, register_separator
from lyraforge.separators import registry as sep_reg
from lyraforge.transcribers import TranscribeOptions, TranscriptionResult, get_transcriber
from lyraforge.transcribers.base import ModelInfo


def _score_from_notes(notes: list[Note], tracks: tuple[TrackInfo, ...]) -> NormalizedScore:
    ordered = sorted(notes, key=lambda n: (n.start_us, n.pitch, n.track, n.channel, n.end_us))
    return NormalizedScore(
        source_sha256="c" * 64,
        midi_type=1 if len(tracks) > 1 else 0,
        ticks_per_beat=500,
        tempo_map=TempoMap(500, [TempoChange(0, 500_000)]),
        time_signatures=(),
        tracks=tracks,
        notes=tuple(ordered),
        duration_us=max((n.end_us for n in ordered), default=0),
        warnings=(),
    )


def _note(
    ms: int,
    dur_ms: int,
    pitch: int,
    *,
    track: int = 0,
    channel: int = 0,
    vel: int = 96,
) -> Note:
    return Note(
        pitch=pitch,
        velocity=vel,
        start_tick=ms,
        end_tick=ms + dur_ms,
        start_us=ms * 1000,
        end_us=(ms + dur_ms) * 1000,
        track=track,
        channel=channel,
    )


def _write_two_level_wav(path: Path, sample_rate: int = 16000) -> None:
    """Write a 2-second mono PCM16 WAV: first 1s quiet (0.04), second 1s loud (0.45)."""
    samples: list[int] = []
    for i in range(sample_rate * 2):
        amp = 0.04 if i < sample_rate else 0.45
        val = int(round(amp * math.sin(2.0 * math.pi * 440.0 * i / sample_rate) * 32767.0))
        samples.append(max(-32767, min(32767, val)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _wav_window_rms(wav_bytes: bytes, start_ms: int, end_ms: int) -> float:
    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    cnt = len(frames) // 2
    vals = struct.unpack(f"<{cnt}h", frames)
    lo = max(0, int(sr * start_ms / 1000))
    hi = min(len(vals), int(sr * end_ms / 1000))
    seg = vals[lo:hi]
    return math.sqrt(sum(v * v for v in seg) / max(1, len(seg)))


def test_stem_dynamics_from_dict_and_section_energy() -> None:
    assert StemDynamics.from_dict(None) is None
    assert StemDynamics.from_dict({}) is None
    assert StemDynamics.from_dict({"vocal_db": "bad"}) is None

    dyn = StemDynamics.from_dict(
        {
            "hop_ms": 500,
            "vocal_db": [-59.0, -24.0, -8.0, -7.0],
            "accomp_db": [-18.0, -16.0, -14.0, -14.0],
        }
    )
    assert dyn is not None
    v0, a0 = dyn.section_energy_at(100)
    v2, _ = dyn.section_energy_at(1100)
    assert v0 == 0.0
    assert v2 is not None and v2 > 0.7
    assert a0 is not None and 0.0 <= a0 <= 1.0


def test_optimize_phrase_octaves_lifts_low_verse_and_preserves_chorus() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    verse = [_note(i * 400, 300, p, track=0) for i, p in enumerate([48, 50, 52, 53, 55, 52])]
    chorus = [
        _note(4000 + i * 400, 300, p, track=0)
        for i, p in enumerate([67, 69, 71, 72, 74, 72])
    ]
    mel_notes = verse + chorus

    shifts_orig, stats_orig = optimize_phrase_octaves(
        mel_notes, 0, profile, PhraseOctaveMode.ORIGINAL
    )
    assert shifts_orig == {}
    assert stats_orig["phrase_shifted_notes"] == 0

    shifts_lift, stats_lift = optimize_phrase_octaves(
        mel_notes, 0, profile, PhraseOctaveMode.SMOOTH_LIFT, has_accompaniment=True
    )
    assert stats_lift["phrases_shifted_up"] >= 1
    assert all(shifts_lift[id(n)] == 12 for n in verse)
    assert all(shifts_lift[id(n)] == 0 for n in chorus)


def test_optimize_phrase_octaves_resists_mid_phrase_octave_jump() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    # Two consecutive sub-phrases separated by only 150ms (too short to break vocally)
    p1 = [_note(i * 200, 150, 58, track=0) for i in range(6)]
    p2 = [_note(1250 + i * 200, 150, 62, track=0) for i in range(6)]
    mel = p1 + p2
    shifts, _ = optimize_phrase_octaves(mel, 0, profile, PhraseOctaveMode.CENTERED)
    assert len({shifts[id(n)] for n in mel}) == 1


def test_align_accompaniment_onsets_snaps_jitter_but_keeps_arpeggios() -> None:
    @dataclass
    class _AccCand:
        at_ms: int

    mel_onsets = [0, 1000, 2000]
    solo_jitter = _AccCand(at_ms=25)
    arp_1 = _AccCand(at_ms=1000)
    arp_2 = _AccCand(at_ms=1020)
    arp_3 = _AccCand(at_ms=1040)
    aligned = align_accompaniment_onsets(
        mel_onsets, [solo_jitter, arp_1, arp_2, arp_3], max_align_ms=35
    )
    assert aligned == 1
    assert solo_jitter.at_ms == 0
    assert (arp_1.at_ms, arp_2.at_ms, arp_3.at_ms) == (1000, 1020, 1040)


def test_vocal_dynamic_thins_climax_keeps_interlude_and_preserves_classic_vocal_lead() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    tracks = (
        TrackInfo(index=0, name="Vocals", note_count=6, channels=(0,)),
        TrackInfo(index=1, name="Guitar", note_count=20, channels=(1,)),
    )
    # Climax melody during 0..2400ms, followed by interlude 3000..5600ms (no melody)
    melody = [_note(i * 400, 300, 72 + (i % 3) * 2, track=0, vel=112) for i in range(6)]
    accomp = [_note(i * 250 + 20, 180, 48 + (i % 3) * 2, track=1, vel=88) for i in range(20)]
    score = _score_from_notes(melody + accomp, tracks)
    dyn = StemDynamics(
        hop_ms=500,
        vocal_db=(-8.0, -7.5, -8.0, -8.5, -8.0, -58.0, -58.0, -58.0, -58.0, -58.0, -58.0),
        accomp_db=(-14.0, -14.0, -14.0, -14.0, -14.0, -11.0, -10.0, -11.0, -11.0, -11.0, -11.0),
    )

    arr_dyn = arrange(
        score,
        profile,
        ArrangeOptions(style=Style.BALANCED, arranger_strategy="vocal_dynamic"),
        stem_dynamics=dyn,
    )
    dyn_stats = arr_dyn.stats["dynamics_adjustments"]
    assert dyn_stats["used_stem_dynamics"] is True
    assert dyn_stats["accomp_thinned"] > 0
    assert dyn_stats["cross_stem_aligned"] > 0
    assert arr_dyn.stats["dropped"].get(DropReason.ACCOMP_THINNED.value, 0) > 0

    climax_acc = [e for e in arr_dyn.events if e.source_track == 1 and e.at_ms < 2500]
    interlude_acc = [e for e in arr_dyn.events if e.source_track == 1 and e.at_ms >= 3000]
    assert len(interlude_acc) > len(climax_acc)

    # Classic and vocal_lead with no overrides remain 100% invariant to stem_dynamics
    for strat in ("classic", "vocal_lead"):
        without_dyn = arrange(
            score, profile, ArrangeOptions(style=Style.BALANCED, arranger_strategy=strat)
        )
        with_dyn = arrange(
            score,
            profile,
            ArrangeOptions(style=Style.BALANCED, arranger_strategy=strat),
            stem_dynamics=dyn,
        )
        assert [e.to_json() for e in without_dyn.events] == [e.to_json() for e in with_dyn.events]


def test_vocal_split_pipeline_extracts_stem_dynamics_into_store_arrange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav_src = tmp_path / "song.wav"
    _write_two_level_wav(wav_src)

    class _MockSep:
        id = "demucs"

        def probe(self) -> Any:
            from lyraforge.separators.base import SeparatorInfo

            return SeparatorInfo(
                id="demucs",
                display_name="Mock Demucs",
                available=True,
                license="MIT",
                scope_note="ok",
            )

        def separate(self, wav_path: Path, out_dir: Path, **_kw: Any) -> SeparatedStems:
            out_dir.mkdir(parents=True, exist_ok=True)
            v = out_dir / "vocals.wav"
            a = out_dir / "no_drums.wav"
            v.write_bytes(wav_path.read_bytes())
            a.write_bytes(wav_path.read_bytes())
            return SeparatedStems(vocals=v, accompaniment=a, metadata={"version": "mock-4"})

    v_score = _score_from_notes(
        [_note(0, 300, 48, track=0), _note(400, 300, 52, track=0)],
        (TrackInfo(index=0, name="Vocals", note_count=2, channels=(0,)),),
    )
    a_score = _score_from_notes(
        [_note(20, 200, 55, track=0), _note(250, 200, 59, track=0)],
        (TrackInfo(index=0, name="Accomp", note_count=2, channels=(0,)),),
    )

    class _MockTrans:
        def __init__(self, eid: str, mid: bytes) -> None:
            self.id = eid
            self._mid = mid

        def probe(self) -> ModelInfo:
            return ModelInfo(
                id=self.id, display_name=self.id, available=True, license="MIT", scope_note="ok"
            )

        def transcribe(self, _wav: Path, **_kw: Any) -> TranscriptionResult:
            return TranscriptionResult(
                engine_id=self.id,
                engine_version="1.0",
                midi_bytes=self._mid,
                note_count=2,
                duration_ms=800,
            )

    def _fake_trans(eid: str = "builtin-mono") -> Any:
        if eid in {"builtin-mono", "basic-pitch", "swift-f0"}:
            return _MockTrans(eid, score_to_midi_bytes(v_score))
        return _MockTrans(eid, score_to_midi_bytes(a_score))

    orig_sep = sep_reg._SEPARATORS["demucs"]
    register_separator(_MockSep())
    monkeypatch.setattr("lyraforge.pipelines.builtin.get_transcriber", _fake_trans)
    monkeypatch.setattr(
        "lyraforge.pipelines.builtin._available_engine_ids", lambda: {"swift-f0", "dettato"}
    )
    monkeypatch.setattr("lyraforge.library.store.get_transcriber", _fake_trans)
    try:
        with LibraryStore(tmp_path / "lib") as store:
            imp = store.import_audio(wav_src, title="Dynamic Stem Test")
            tr = store.transcribe_song(imp.song.id, pipeline_id="vocal_split_full")
            assert "stem_dynamics" in tr.metadata
            assert len(tr.metadata["stem_dynamics"]["vocal_db"]) >= 3

            arr = store.arrange_song(
                imp.song.id,
                transcription_id=tr.id,
                options=ArrangeOptions(style=Style.BALANCED, arranger_strategy="vocal_dynamic"),
            )
            report = store.load_arrangement_report(arr.id)
            dyn_adj = report["stats"]["dynamics_adjustments"]
            assert dyn_adj["used_stem_dynamics"] is True
            assert dyn_adj["accomp_density"] == AccompDensity.AUTO.value
    finally:
        register_separator(orig_sep)
        # Silence unused import warning cleanly while keeping coverage explicit
        assert get_pipeline("vocal_split_full") is not None
        assert PipelineRequest is not None
        assert TranscribeOptions is not None
        assert get_transcriber is not None


def test_fixed_velocity_preview_synth_api_cache_cli_and_mcp_parity(tmp_path: Path) -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    two_vel_score = _score_from_notes(
        [
            _note(0, 200, 60, track=0, vel=20),
            _note(450, 200, 60, track=0, vel=120),
        ],
        (TrackInfo(index=0, name="Lead", note_count=2, channels=(0,)),),
    )
    perf = build_performance(two_vel_score, profile, arrange(two_vel_score, profile))
    dyn_wav = synthesize_performance(perf, fixed_velocity=False)
    fixed_wav = synthesize_performance(perf, fixed_velocity=True)

    # Dynamic velocity: vel=20 note in 0..220ms is much quieter than vel=120 note in 450..670ms
    assert _wav_window_rms(dyn_wav, 10, 220) < _wav_window_rms(dyn_wav, 460, 670) * 0.45
    # Fixed game velocity: amplitude across identical-pitch notes is uniform regardless of velocity
    assert math.isclose(
        _wav_window_rms(fixed_wav, 10, 220),
        _wav_window_rms(fixed_wav, 460, 670),
        rel_tol=0.05,
    )

    # Full API + CLI + MCP integration with a minimal multi-track MIDI file
    mid_path = tmp_path / "duo.mid"
    duo = _score_from_notes(
        [
            _note(0, 300, 48, track=0, vel=110),
            _note(400, 300, 50, track=0, vel=110),
            _note(20, 200, 55, track=1, vel=80),
            _note(220, 200, 59, track=1, vel=80),
        ],
        (
            TrackInfo(index=0, name="Lead", note_count=2, channels=(0,)),
            TrackInfo(index=1, name="Guitar", note_count=2, channels=(1,)),
        ),
    )
    mid_path.write_bytes(score_to_midi_bytes(duo))

    data_dir = tmp_path / "app_data"
    token = "dyn-tok"
    app = create_app(data_dir=data_dir, session_token=token)
    headers = {SESSION_TOKEN_HEADER: token}
    client = TestClient(app)

    with mid_path.open("rb") as fh:
        imp = client.post(
            "/v1/imports",
            headers=headers,
            files={"file": ("duo.mid", fh, "audio/midi")},
            data={"title": "Duo"},
        ).json()
    song_id = imp["song"]["id"]

    arr_resp = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={
            "song_id": song_id,
            "style": "balanced",
            "arranger_strategy": "vocal_dynamic",
            "accomp_density": "auto",
            "phrase_octave_mode": "smooth_lift",
            "cross_stem_align_ms": 30,
        },
    )
    assert arr_resp.status_code == 200
    arr_id = arr_resp.json()["arrangement"]["id"]

    p_fixed = client.post(
        "/v1/preview",
        headers=headers,
        json={"arrangement_id": arr_id, "fixed_velocity": True},
    )
    assert p_fixed.status_code == 200
    assert p_fixed.json()["fixed_velocity"] is True
    assert "fixed_velocity=1" in p_fixed.json()["preview_url"]

    fixed_wav_file = data_dir / "songs" / song_id / "previews" / f"{arr_id}.fixed.wav"
    assert fixed_wav_file.is_file()
    wav_resp = client.get(p_fixed.json()["preview_url"], headers=headers)
    assert wav_resp.status_code == 200
    assert wav_resp.content[:4] == b"RIFF"

    del_resp = client.delete(f"/v1/arrangements/{arr_id}", headers=headers)
    assert del_resp.status_code == 200
    assert not fixed_wav_file.exists()

    # CLI arrange + preview --fixed-velocity parity
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(
            [
                "library",
                "arrange",
                song_id,
                "--data-dir",
                str(data_dir),
                "--arranger-strategy",
                "vocal_dynamic",
                "--accomp-density",
                "auto",
                "--phrase-octave-mode",
                "smooth_lift",
                "--cross-stem-align-ms",
                "25",
            ]
        )
    assert rc == 0
    cli_arr_id = json.loads(buf.getvalue())["id"]

    buf_prev = io.StringIO()
    with redirect_stdout(buf_prev):
        rc_p = cli_main(
            [
                "preview",
                cli_arr_id,
                "--data-dir",
                str(data_dir),
                "--fixed-velocity",
            ]
        )
    assert rc_p == 0
    assert json.loads(buf_prev.getvalue())["wav_path"].endswith(".fixed.wav")

    # MCP arrange & preview parity
    with LibraryStore(data_dir) as store:
        server = LyraMCPServer(MCPToolExecutor(store, tasks=MCPTaskRegistry()))
        init_resp = server.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 20,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "1.0"},
                    },
                }
            )
        )
        assert init_resp is not None and "result" in init_resp
        server.handle_message(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        mcp_arr = server.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 21,
                    "method": "tools/call",
                    "params": {
                        "name": "arrange",
                        "arguments": {
                            "song_id": song_id,
                            "arranger_strategy": "vocal_dynamic",
                            "accomp_density": "minimal",
                            "phrase_octave_mode": "centered",
                            "cross_stem_align_ms": 20,
                        },
                    },
                }
            )
        )
        assert mcp_arr is not None and "result" in mcp_arr
        mcp_arr_id = json.loads(mcp_arr["result"]["content"][0]["text"])["arrangement"]["id"]
        mcp_prev = server.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 22,
                    "method": "tools/call",
                    "params": {
                        "name": "preview",
                        "arguments": {"arrangement_id": mcp_arr_id, "fixed_velocity": True},
                    },
                }
            )
        )
        assert mcp_prev is not None and "result" in mcp_prev
        prev_payload = json.loads(mcp_prev["result"]["content"][0]["text"])
        assert prev_payload["fixed_velocity"] is True
        assert prev_payload["wav_path"].endswith(".fixed.wav")
