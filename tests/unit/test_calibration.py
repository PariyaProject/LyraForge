"""Unit and integration tests for 3-tier instrument calibration benchmark & WAV analysis."""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.cli import EXIT_OK, main
from lyraforge.instruments import load_builtin_profile
from lyraforge.library.store import LibraryStore
from lyraforge.mcp import MCPTaskRegistry, MCPToolExecutor
from lyraforge.music_core.performance import validate_performance
from lyraforge.playback.calibration import (
    CALIBRATION_PATTERNS,
    analyze_calibration_recording,
    build_calibration_performance,
    list_calibration_patterns,
    run_calibration_benchmark,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _render_synthetic_wav(
    segments_with_tones: list[tuple[float, float, float, float]],
    *,
    total_ms: int,
    sample_rate: int = 22_050,
    noise_amp: float = 0.002,
) -> bytes:
    """Render deterministic PCM16 mono WAV from ``(onset_ms, decay_ms, freq_hz, amp)`` tuples."""
    n_samples = int(round(total_ms * sample_rate / 1000.0))
    buf = [0.0] * n_samples
    for onset_ms, decay_ms, freq_hz, amp in segments_with_tones:
        start_idx = max(0, int(round(onset_ms * sample_rate / 1000.0)))
        dur_samples = max(1, int(round(decay_ms * 3.0 * sample_rate / 1000.0)))
        for j in range(dur_samples):
            idx = start_idx + j
            if idx >= n_samples:
                break
            t_s = j / sample_rate
            env = math.exp(-t_s / max(0.01, decay_ms / 1000.0))
            buf[idx] += amp * env * math.sin(2.0 * math.pi * freq_hz * t_s)
    pcm = bytearray()
    for i, val in enumerate(buf):
        dither = noise_amp * math.sin(i * 0.71)
        clamped = max(-0.98, min(0.98, val + dither))
        pcm.extend(struct.pack("<h", int(clamped * 32767)))
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(pcm))
    return out.getvalue()


def test_all_seven_calibration_patterns_build_valid_performances() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    listed = list_calibration_patterns()
    assert [p["code"] for p in listed] == ["A", "B", "C", "D", "E", "F", "G"]
    for pat_id in CALIBRATION_PATTERNS:
        built = build_calibration_performance(
            pat_id,
            profile,
            duration_s=2.0 if pat_id == "long_stability" else None,
        )
        perf = built["performance"]
        validate_performance(perf, profile)
        assert perf["events"]
        assert built["segments"]


def test_calibration_tiers_1_and_2_verify_zero_overlaps_and_honest_flag() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    patterns_to_check = (
        "distinct_key_rapid",
        "same_key_retrigger",
        "chord_simultaneous",
        "rapid_arpeggio",
        "hold_release_sweep",
    )
    for pat_id in patterns_to_check:
        res_v = run_calibration_benchmark(pat_id, profile, realtime=False)
        assert res_v["tier"] == "dry_run_virtual"
        assert res_v["verifies_game_audio"] is False
        assert res_v["log_verification"]["overlapping_key_downs"] == 0

    res_rt = run_calibration_benchmark("rapid_arpeggio", profile, realtime=True)
    assert res_rt["tier"] == "realtime_scheduler"
    assert res_rt["verifies_game_audio"] is False
    assert res_rt["log_verification"]["overlapping_key_downs"] == 0
    assert res_rt["result"]["actions_sent"] == res_rt["expected_events"] * 2
    assert res_rt["cpu_pct"] >= 0.0


def test_analyze_calibration_recording_recovers_offset_and_thresholds() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")

    # Pattern B (same_key_retrigger): +60ms offset, drop <60ms repeats
    built_b = build_calibration_performance("same_key_retrigger", profile)
    events_b = built_b["performance"]["events"]
    offset_ms = 60.0
    tones_b: list[tuple[float, float, float, float]] = []
    last_emit = -1e9
    for ev in events_b:
        at = float(ev["at_ms"])
        if at - last_emit >= 60.0:
            tones_b.append((at + offset_ms, 55.0, 523.25, 0.7))
            last_emit = at
    wav_b = _render_synthetic_wav(tones_b, total_ms=built_b["performance"]["duration_ms"] + 400)
    report_b = analyze_calibration_recording(
        wav_b,
        events_b,
        pattern_id="same_key_retrigger",
        segments=built_b["segments"],
        tolerance_ms=45.0,
    )
    assert report_b["measurement_basis"] == "recorded_audio_onset_analysis"
    assert abs(report_b["estimated_offset_ms"] - offset_ms) <= 15.0
    assert report_b["matched_onsets"] >= 18
    assert report_b["suggested_timing"]["min_same_key_interval_ms"] >= 60

    # Pattern D (rapid_arpeggio): all hits >= 15ms present
    built_d = build_calibration_performance("rapid_arpeggio", profile)
    tones_d = [
        (float(ev["at_ms"]) + 20.0, 50.0, 440.0 + i * 15, 0.65)
        for i, ev in enumerate(built_d["performance"]["events"])
    ]
    wav_d = _render_synthetic_wav(tones_d, total_ms=built_d["performance"]["duration_ms"] + 400)
    report_d = analyze_calibration_recording(
        wav_d,
        built_d["performance"]["events"],
        pattern_id="rapid_arpeggio",
        segments=built_d["segments"],
        tolerance_ms=40.0,
    )
    assert report_d["detection_rate"] >= 0.80
    assert "min_inter_key_interval_ms" in report_d["suggested_timing"]

    # Pattern E (hold_release_sweep): drops hold<25ms, detects hold>=25ms & gap>=20ms
    built_e = build_calibration_performance("hold_release_sweep", profile)
    tones_e = [
        (float(ev["at_ms"]) + 25.0, 45.0, 523.25, 0.7)
        for ev in built_e["performance"]["events"]
        if int(ev["hold_ms"]) >= 25
    ]
    wav_e = _render_synthetic_wav(tones_e, total_ms=built_e["performance"]["duration_ms"] + 400)
    report_e = analyze_calibration_recording(
        wav_e,
        built_e["performance"]["events"],
        pattern_id="hold_release_sweep",
        segments=built_e["segments"],
        tolerance_ms=40.0,
    )
    assert report_e["suggested_timing"]["min_key_hold_ms"] == 25

    # Pattern G: one-shot (constant short decay) vs sustained (longer decay when held 350ms)
    built_g = build_calibration_performance("instrument_sustain_trigger", profile)
    tones_one_shot = [
        (float(ev["at_ms"]) + 10.0, 80.0, 392.0, 0.7) for ev in built_g["performance"]["events"]
    ]
    wav_one_shot = _render_synthetic_wav(
        tones_one_shot, total_ms=built_g["performance"]["duration_ms"] + 1200
    )
    rep_os = analyze_calibration_recording(
        wav_one_shot,
        built_g["performance"]["events"],
        pattern_id="instrument_sustain_trigger",
        segments=built_g["segments"],
    )
    assert rep_os["suggested_timing"]["trigger_mode"] == "one_shot"

    tones_sustained = [
        (float(ev["at_ms"]) + 10.0, 260.0 if int(ev["hold_ms"]) >= 300 else 65.0, 392.0, 0.7)
        for ev in built_g["performance"]["events"]
    ]
    wav_sustained = _render_synthetic_wav(
        tones_sustained, total_ms=built_g["performance"]["duration_ms"] + 1200
    )
    rep_sus = analyze_calibration_recording(
        wav_sustained,
        built_g["performance"]["events"],
        pattern_id="instrument_sustain_trigger",
        segments=built_g["segments"],
    )
    assert rep_sus["suggested_timing"]["trigger_mode"] == "sustained"


def test_api_calibration_endpoints_and_timing_mode_options(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path / "api", session_token="tok-cal")
    headers = {SESSION_TOKEN_HEADER: "tok-cal"}
    client = TestClient(app)

    pats = client.get("/v1/calibration/patterns", headers=headers)
    assert pats.status_code == 200
    assert len(pats.json()["patterns"]) == 7

    dry = client.post(
        "/v1/calibration/run-dry",
        headers=headers,
        json={"pattern_id": "same_key_retrigger", "realtime": False},
    )
    assert dry.status_code == 200
    assert dry.json()["tier"] == "dry_run_virtual"
    assert dry.json()["log_verification"]["overlapping_key_downs"] == 0

    prep = client.post(
        "/v1/calibration/prepare",
        headers=headers,
        json={
            "pattern_id": "chord_simultaneous",
            "mode": "dry-run",
            "realtime": False,
            "late_event_policy": "shift_clock",
        },
    )
    assert prep.status_code == 200
    tok = prep.json()["prepare_token"]
    started = client.post("/v1/playback/start", headers=headers, json={"prepare_token": tok})
    assert started.status_code == 200
    for _ in range(30):
        st = client.get("/v1/playback/status", headers=headers).json()
        if st["state"] not in {"running", "waiting_focus"}:
            break
        time.sleep(0.05)
    assert st["state"] == "completed"
    assert st["last_result"]["p50_lateness_ms"] is not None

    # Upload WAV analysis
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    built_d = build_calibration_performance("rapid_arpeggio", profile)
    wav_d = _render_synthetic_wav(
        [(float(e["at_ms"]) + 10.0, 45.0, 440.0, 0.7) for e in built_d["performance"]["events"]],
        total_ms=built_d["performance"]["duration_ms"] + 300,
    )
    ana = client.post(
        "/v1/calibration/analyze",
        headers=headers,
        files={"file": ("cal.wav", wav_d, "audio/wav")},
        data={"pattern_id": "rapid_arpeggio", "tolerance_ms": "45"},
    )
    assert ana.status_code == 200
    assert ana.json()["detection_rate"] >= 0.80

    # Import MIDI and arrange with timing_mode + prepare with timing overrides
    with (FIXTURE_DIR / "chords_type1.mid").open("rb") as fh:
        imp = client.post(
            "/v1/imports",
            headers=headers,
            files={"file": ("chords.mid", fh, "audio/midi")},
        )
    assert imp.status_code == 200
    song_id = imp.json()["song"]["id"]

    arr_resp = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "timing_mode": "strict_fidelity", "arpeggiate_ms": 12},
    )
    assert arr_resp.status_code == 200
    arr_id = arr_resp.json()["arrangement"]["id"]
    detail = client.get(f"/v1/arrangements/{arr_id}", headers=headers).json()
    assert detail["report"]["stats"]["timing_mode"] == "strict_fidelity"

    pb_prep = client.post(
        "/v1/playback/prepare",
        headers=headers,
        json={
            "arrangement_id": arr_id,
            "mode": "dry-run",
            "realtime": False,
            "min_key_release_gap_ms": 25,
            "key_hold_ms": 30,
            "late_event_policy": "drop_late",
        },
    )
    assert pb_prep.status_code == 200
    assert pb_prep.json()["min_key_release_gap_ms"] == 25
    assert pb_prep.json()["late_event_policy"] == "drop_late"


def test_cli_calibrate_and_mcp_arrange_timing_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    assert main(["calibrate", "list"]) == EXIT_OK
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["patterns"]) == 7

    assert main(["calibrate", "run", "same_key_retrigger"]) == EXIT_OK
    run_out = json.loads(capsys.readouterr().out)
    assert run_out["log_verification"]["overlapping_key_downs"] == 0

    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    built_b = build_calibration_performance("same_key_retrigger", profile)
    wav_path = tmp_path / "b.wav"
    tones_b_cli = [
        (float(e["at_ms"]) + 20.0, 50.0, 523.25, 0.7) for e in built_b["performance"]["events"]
    ]
    wav_path.write_bytes(
        _render_synthetic_wav(tones_b_cli, total_ms=built_b["performance"]["duration_ms"] + 300)
    )
    rc = main(["calibrate", "analyze", str(wav_path), "--pattern", "same_key_retrigger"])
    assert rc == EXIT_OK
    ana_out = json.loads(capsys.readouterr().out)
    assert ana_out["matched_onsets"] >= 16

    with LibraryStore(tmp_path / "mcp_lib") as store:
        executor = MCPToolExecutor(store, tasks=MCPTaskRegistry())
        imp, imp_err = executor.call(
            "import_media", {"path": str(FIXTURE_DIR / "chords_type1.mid")}
        )
        assert not imp_err
        arr, arr_err = executor.call(
            "arrange",
            {
                "song_id": imp["song"]["id"],
                "style": "balanced",
                "arpeggiate_ms": 12,
                "timing_mode": "adapted",
            },
        )
        assert not arr_err
        assert arr["arrangement"]["event_count"] > 0
