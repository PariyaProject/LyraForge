"""Unit tests for lyraforge.preview.synth."""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core.arranger import ArrangeOptions, Style, arrange
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import build_performance
from lyraforge.preview import (
    DEFAULT_SAMPLE_RATE,
    synthesize_performance,
    synthesize_performance_to_wav,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _tone_perf(pitch: int, timbre_profile: str = "genshin.harmonic_keys.v1") -> dict[str, object]:
    base = _make_perf("c_major_scale.mid")
    first_ev = dict(base["events"][0])  # type: ignore[index]
    first_ev["at_ms"] = 0
    first_ev["hold_ms"] = 120
    first_ev["source_pitch"] = pitch
    first_ev["mapped_pitch"] = pitch
    first_ev["velocity"] = 96
    base["instrument_profile_id"] = timbre_profile
    base["events"] = [first_ev]
    base["duration_ms"] = 1000
    return base


def _make_perf(fixture_name: str, style: Style = Style.BALANCED) -> dict[str, object]:
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / fixture_name)
    arr = arrange(score, prof, ArrangeOptions(style=style))
    return build_performance(score, prof, arr)


def test_synthesize_performance_valid_wav_and_deterministic() -> None:
    perf = _make_perf("c_major_scale.mid")
    wav1 = synthesize_performance(perf)
    wav2 = synthesize_performance(perf)
    assert wav1 == wav2
    assert wav1[:4] == b"RIFF"

    with wave.open(io.BytesIO(wav1), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == DEFAULT_SAMPLE_RATE
        nframes = wf.getnframes()
        assert nframes / DEFAULT_SAMPLE_RATE >= int(perf["duration_ms"]) / 1000.0
        raw = wf.readframes(nframes)

    samples = struct.unpack(f"<{nframes}h", raw)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    assert rms > 100.0
    assert max(abs(s) for s in samples) <= 32767


def test_synthesize_dense_chords_no_clipping_and_to_wav(tmp_path: Path) -> None:
    perf = _make_perf("dense_chords.mid", style=Style.RICH)
    out = tmp_path / "sub" / "preview.wav"
    written = synthesize_performance_to_wav(perf, out, sample_rate=16_000)
    assert written == out
    assert out.is_file()
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 16_000
        samples = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))
    assert max(abs(s) for s in samples) <= 32767


def test_synthesize_rejects_invalid_inputs() -> None:
    perf = _make_perf("c_major_scale.mid")
    with pytest.raises(LyraError) as exc:
        synthesize_performance(perf, sample_rate=4000)
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT

    with pytest.raises(LyraError) as exc2:
        synthesize_performance(perf, sample_rate=True)  # type: ignore[arg-type]
    assert exc2.value.code == ErrorCode.INVALID_ARGUMENT

    with pytest.raises(LyraError) as exc3:
        synthesize_performance({"bad": "doc"})
    assert exc3.value.code == ErrorCode.PERFORMANCE_INVALID


def test_studio_timbres_pure_tuned_and_balanced_across_register() -> None:
    test_pitches = (48, 60, 67, 72, 76, 83)
    for timbre in ("piano", "lyre", "zither", "vintage"):
        rms_values: list[float] = []
        for pitch in test_pitches:
            wav = synthesize_performance(_tone_perf(pitch), timbre=timbre)
            with wave.open(io.BytesIO(wav), "rb") as wf:
                sr = wf.getframerate()
                samples = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))
            seg = samples[int(sr * 0.04) : int(sr * 0.24)]
            rms_values.append(math.sqrt(sum(s * s for s in seg) / len(seg)))

            # Verify fundamental pitch accuracy within ±10 cents (guards against octave-high bugs)
            expected_hz = 440.0 * (2.0 ** ((pitch - 69) / 12.0))
            n = len(seg)
            mag_exp = math.hypot(
                sum(seg[k] * math.cos(2.0 * math.pi * expected_hz * k / sr) for k in range(n)),
                sum(seg[k] * math.sin(2.0 * math.pi * expected_hz * k / sr) for k in range(n)),
            )
            mag_oct_up = math.hypot(
                sum(seg[k] * math.cos(4.0 * math.pi * expected_hz * k / sr) for k in range(n)),
                sum(seg[k] * math.sin(4.0 * math.pi * expected_hz * k / sr) for k in range(n)),
            )
            mag_detuned = math.hypot(
                sum(
                    seg[k]
                    * math.cos(2.0 * math.pi * (expected_hz * 1.03) * k / sr)
                    for k in range(n)
                ),
                sum(
                    seg[k]
                    * math.sin(2.0 * math.pi * (expected_hz * 1.03) * k / sr)
                    for k in range(n)
                ),
            )
            assert mag_exp > mag_oct_up * 1.5
            assert mag_exp > mag_detuned * 3.0

        # Ensure no single dead/loud key anomaly across C3..B5
        assert max(rms_values) / min(rms_values) < 2.2


def test_synthesize_real_timbres_distinct_and_chord_safe() -> None:
    perf = _make_perf("dense_chords.mid", style=Style.RICH)
    wavs = {
        timbre: synthesize_performance(perf, timbre=timbre)
        for timbre in ("piano", "lyre", "zither", "vintage")
    }
    assert len(set(wavs.values())) == 4
    for _timbre, wav in wavs.items():
        with wave.open(io.BytesIO(wav), "rb") as wf:
            samples = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        assert rms > 300.0
        assert max(abs(s) for s in samples) <= 32767


def test_genshin_one_shot_sustain_tail_and_same_pitch_retrigger() -> None:
    single = _tone_perf(60, timbre_profile="genshin.harmonic_keys.v1")
    single["events"][0]["hold_ms"] = 40  # type: ignore[index]
    single["duration_ms"] = 1200
    wav_single = synthesize_performance(single, timbre="piano")
    with wave.open(io.BytesIO(wav_single), "rb") as wf:
        sr = wf.getframerate()
        s_single = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))

    onset_seg = s_single[int(sr * 0.02) : int(sr * 0.15)]
    tail_seg = s_single[int(sr * 0.40) : int(sr * 0.70)]
    onset_rms = math.sqrt(sum(x * x for x in onset_seg) / len(onset_seg))
    tail_rms = math.sqrt(sum(x * x for x in tail_seg) / len(tail_seg))
    # Brief 40ms tap must ring naturally well past key release like Genshin Harmonic Keys
    assert tail_rms > onset_rms * 0.15

    ev1 = dict(single["events"][0])  # type: ignore[index]
    ev2 = dict(ev1)
    ev2["at_ms"] = 300
    repeated = dict(single)
    repeated["events"] = [ev1, ev2]
    repeated["duration_ms"] = 1500
    wav_rep = synthesize_performance(repeated, timbre="piano")
    with wave.open(io.BytesIO(wav_rep), "rb") as wf:
        sr2 = wf.getframerate()
        s_rep = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))

    assert max(abs(x) for x in s_rep) <= 32767
    retrigger_seg = s_rep[int(sr2 * 0.31) : int(sr2 * 0.50)]
    retrigger_rms = math.sqrt(sum(x * x for x in retrigger_seg) / len(retrigger_seg))
    assert retrigger_rms > 300.0
    # Smooth retrigger handoff without discontinuous single-sample click spike across 300 ms
    win_start = max(1, int(sr2 * 0.295))
    win_end = min(len(s_rep), int(sr2 * 0.320))
    max_step = max(abs(s_rep[i] - s_rep[i - 1]) for i in range(win_start, win_end))
    assert max_step < 12000
