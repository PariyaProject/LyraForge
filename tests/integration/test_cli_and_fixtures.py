"""Integration tests: fixture determinism and end-to-end CLI workflows."""

from __future__ import annotations

import json
import sqlite3
import sys
import wave
from pathlib import Path

import pytest

from lyraforge.cli import EXIT_ERROR, EXIT_OK, EXIT_PLAYBACK_INCOMPLETE, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from midi_builders import FIXTURES  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_committed_midi_fixtures_match_builders_byte_for_byte() -> None:
    for rel_name, builder in FIXTURES.items():
        path = FIXTURE_DIR / rel_name
        assert path.is_file(), f"Missing fixture file: {path}"
        assert path.read_bytes() == builder(), f"Fixture drift detected in {rel_name}"


def test_cli_profiles_inspect_arrange_validate_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["profiles", "list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "genshin.windsong_lyre.v1" in out

    assert main(["profiles", "show", "genshin.windsong_lyre.v1"]) == EXIT_OK
    prof_json = json.loads(capsys.readouterr().out)
    assert prof_json["key_count"] == 21
    assert prof_json["_hash"].startswith("sha256:")

    midi_path = FIXTURE_DIR / "chords_type1.mid"
    assert main(["inspect", str(midi_path)]) == EXIT_OK
    insp = json.loads(capsys.readouterr().out)
    assert insp["note_count"] == 28
    assert insp["midi_type"] == 1

    perf_a = tmp_path / "perf_a.json"
    perf_b = tmp_path / "perf_b.json"
    rep_a = tmp_path / "report_a.json"
    assert main(["arrange", str(midi_path), "-o", str(perf_a), "--report", str(rep_a)]) == EXIT_OK
    assert main(["arrange", str(midi_path), "-o", str(perf_b)]) == EXIT_OK
    assert perf_a.read_bytes() == perf_b.read_bytes()
    capsys.readouterr()

    assert main(["validate", str(perf_a)]) == EXIT_OK
    val_out = capsys.readouterr().out
    assert "OK:" in val_out

    log_path = tmp_path / "dryrun.jsonl"
    assert main(["playback", "dry-run", str(perf_a), "--log", str(log_path)]) == EXIT_OK
    pb_summary = json.loads(capsys.readouterr().out)
    assert pb_summary["state"] == "completed"
    assert pb_summary["sent_os_input"] is False
    assert pb_summary["keys_still_pressed"] == []
    assert pb_summary["actions_sent"] == pb_summary["actions_total"] > 0

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == pb_summary["actions_total"]

    rc_stop = main(["playback", "dry-run", str(perf_a), "--stop-after-ms", "500"])
    assert rc_stop == EXIT_PLAYBACK_INCOMPLETE
    stop_summary = json.loads(capsys.readouterr().out)
    assert stop_summary["state"] == "stopped"
    assert stop_summary["keys_still_pressed"] == []


def test_cli_error_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", str(FIXTURE_DIR / "broken" / "not_midi.mid")]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "MEDIA_DECODE_FAILED" in err

    assert main(["arrange", str(FIXTURE_DIR / "empty.mid")]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "NO_PLAYABLE_NOTES" in err

    bad_perf = tmp_path / "bad.json"
    bad_perf.write_text("{invalid json", encoding="utf-8")
    assert main(["validate", str(bad_perf)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "PERFORMANCE_INVALID" in err


def test_cli_library_import_arrange_preview_and_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "lib_data"
    midi_path = FIXTURE_DIR / "chords_type1.mid"

    assert (
        main(
            [
                "import",
                str(midi_path),
                "--title",
                "Chords Integration",
                "--artist",
                "Tester",
                "--tags",
                "demo,lyre",
                "--data-dir",
                str(data_dir),
            ]
        )
        == EXIT_OK
    )
    imp = json.loads(capsys.readouterr().out)
    assert imp["deduplicated"] is False
    song_id = imp["song"]["id"]

    assert main(["library", "list", "--data-dir", str(data_dir)]) == EXIT_OK
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 1
    assert listed[0]["id"] == song_id

    assert main(["library", "search", "Chords", "--data-dir", str(data_dir)]) == EXIT_OK
    searched = json.loads(capsys.readouterr().out)
    assert len(searched) == 1

    assert (
        main(
            [
                "library",
                "arrange",
                song_id,
                "--style",
                "balanced",
                "--data-dir",
                str(data_dir),
            ]
        )
        == EXIT_OK
    )
    arr_rec = json.loads(capsys.readouterr().out)
    arr_id = arr_rec["id"]

    assert main(["library", "show", song_id, "--data-dir", str(data_dir)]) == EXIT_OK
    detail = json.loads(capsys.readouterr().out)
    assert len(detail["arrangements"]) == 1

    copied_wav = tmp_path / "out_preview.wav"
    assert (
        main(
            [
                "preview",
                arr_id,
                "-o",
                str(copied_wav),
                "--data-dir",
                str(data_dir),
            ]
        )
        == EXIT_OK
    )
    pv = json.loads(capsys.readouterr().out)
    assert pv["arrangement_id"] == arr_id
    assert copied_wav.is_file()
    with wave.open(str(copied_wav), "rb") as wf:
        assert wf.getnframes() > 0

    assert main(["playback", "dry-run", arr_id, "--data-dir", str(data_dir)]) == EXIT_OK
    pb = json.loads(capsys.readouterr().out)
    assert pb["state"] == "completed"
    assert pb["sent_os_input"] is False

    conn = sqlite3.connect(data_dir / "library.db")
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM playback_sessions").fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()

    # Direct performance.json file preview requires -o
    perf_path = data_dir / arr_rec["performance_path"]
    assert main(["preview", str(perf_path)]) == EXIT_ERROR
    assert "INVALID_ARGUMENT" in capsys.readouterr().err

    direct_wav = tmp_path / "direct.wav"
    assert main(["preview", str(perf_path), "-o", str(direct_wav)]) == EXIT_OK
    capsys.readouterr()
    assert direct_wav.is_file()


def test_cli_engines_and_transcribe_wav_to_lyre(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["engines", "list"]) == EXIT_OK
    engines = json.loads(capsys.readouterr().out)
    assert any(e["id"] == "builtin-mono" and e["available"] for e in engines)

    perf = tmp_path / "scale.json"
    wav = tmp_path / "scale.wav"
    assert main(["arrange", str(FIXTURE_DIR / "c_major_scale.mid"), "-o", str(perf)]) == EXIT_OK
    capsys.readouterr()
    assert main(["preview", str(perf), "-o", str(wav)]) == EXIT_OK
    capsys.readouterr()

    raw_mid = tmp_path / "raw.mid"
    clean_mid = tmp_path / "cleaned.mid"
    out_perf = tmp_path / "transcribed_perf.json"
    assert (
        main(
            [
                "transcribe",
                str(wav),
                "--engine",
                "builtin-mono",
                "-o",
                str(raw_mid),
                "--cleaned-out",
                str(clean_mid),
                "--arrange-out",
                str(out_perf),
            ]
        )
        == EXIT_OK
    )
    tr_summary = json.loads(capsys.readouterr().out)
    assert tr_summary["cleaned_note_count"] >= 6
    assert raw_mid.is_file() and clean_mid.is_file() and out_perf.is_file()
    assert main(["validate", str(out_perf)]) == EXIT_OK
    capsys.readouterr()

    # Unified import of WAV + export command
    lib_dir = tmp_path / "cli_audio_lib"
    assert main(["import", str(wav), "--title", "CLI WAV", "--data-dir", str(lib_dir)]) == EXIT_OK
    imp = json.loads(capsys.readouterr().out)
    assert imp["source"]["kind"] == "audio"

    # Export MIDI and JSON from existing MIDI arrangement
    assert (
        main(["import", str(FIXTURE_DIR / "c_major_scale.mid"), "--data-dir", str(lib_dir)])
        == EXIT_OK
    )
    mid_song_id = json.loads(capsys.readouterr().out)["song"]["id"]
    assert main(["library", "arrange", mid_song_id, "--data-dir", str(lib_dir)]) == EXIT_OK
    arr_id = json.loads(capsys.readouterr().out)["id"]

    exp_mid = tmp_path / "exported.mid"
    exp_json = tmp_path / "exported.json"
    assert (
        main(
            [
                "export",
                arr_id,
                "--format",
                "midi",
                "-o",
                str(exp_mid),
                "--data-dir",
                str(lib_dir),
            ]
        )
        == EXIT_OK
    )
    capsys.readouterr()
    assert exp_mid.read_bytes().startswith(b"MThd")

    assert (
        main(
            [
                "export",
                arr_id,
                "--format",
                "json",
                "-o",
                str(exp_json),
                "--data-dir",
                str(lib_dir),
            ]
        )
        == EXIT_OK
    )
    capsys.readouterr()
    assert json.loads(exp_json.read_text(encoding="utf-8"))["arrangement_id"] == arr_id
