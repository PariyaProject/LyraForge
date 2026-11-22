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
