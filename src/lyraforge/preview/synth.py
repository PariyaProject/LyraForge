"""Offline plucked-lyre WAV preview synthesizer (pure cross-platform stdlib).

Renders a validated ``performance.json`` to mono 16-bit PCM WAV without any
external soundfonts, game samples, or native audio libraries.
"""

from __future__ import annotations

import array
import io
import math
import sys
import wave
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes
from lyraforge.music_core.performance import validate_performance

DEFAULT_SAMPLE_RATE = 22_050
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 48_000

_ATTACK_S = 0.005
_DECAY_RATE = 4.2
_TAIL_MIN_S = 0.45
_TAIL_MAX_S = 1.20
_END_PAD_S = 0.25
_TARGET_PEAK = 0.85


def _midi_pitch_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _render_note(
    buf: list[float],
    *,
    start_idx: int,
    pitch: int,
    velocity: int,
    hold_ms: int,
    sample_rate: int,
) -> None:
    freq = _midi_pitch_to_hz(pitch)
    w = 2.0 * math.pi * freq / sample_rate
    note_dur_s = min(max(hold_ms / 1000.0 + 0.35, _TAIL_MIN_S), _TAIL_MAX_S)
    total_samples = max(1, int(round(note_dur_s * sample_rate)))
    attack_samples = max(1, int(round(_ATTACK_S * sample_rate)))
    amp = (velocity / 127.0) * 0.45
    limit = min(len(buf), start_idx + total_samples)
    fade_out_start = max(attack_samples, total_samples - int(round(0.04 * sample_rate)))

    for offset in range(limit - start_idx):
        t = offset / sample_rate
        if offset < attack_samples:
            env = offset / attack_samples
        else:
            env = math.exp(-_DECAY_RATE * (t - _ATTACK_S))
        if offset > fade_out_start and total_samples > fade_out_start:
            env *= (total_samples - offset) / (total_samples - fade_out_start)
        wave_val = (
            math.sin(w * offset)
            + 0.35 * math.sin(2.0 * w * offset) * math.exp(-5.0 * t)
            + 0.15 * math.sin(3.0 * w * offset) * math.exp(-9.0 * t)
        )
        buf[start_idx + offset] += amp * env * wave_val


def _check_cancel(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "preview synthesis cancelled")


def synthesize_performance(
    doc: Mapping[str, Any],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    fixed_velocity: bool = False,
    is_cancelled: Callable[[], bool] | None = None,
) -> bytes:
    """Render a performance document to mono 16-bit PCM WAV bytes."""
    _check_cancel(is_cancelled)
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or not (
        MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE
    ):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"sample_rate must be an int in [{MIN_SAMPLE_RATE}, {MAX_SAMPLE_RATE}]",
            {"sample_rate": sample_rate},
        )
    validate_performance(doc)

    events = doc["events"]
    max_end_s = max(
        (e["at_ms"] / 1000.0) + min(max(e["hold_ms"] / 1000.0 + 0.35, _TAIL_MIN_S), _TAIL_MAX_S)
        for e in events
    )
    total_samples = max(1, int(math.ceil((max_end_s + _END_PAD_S) * sample_rate)))
    buf = [0.0] * total_samples

    for e in events:
        _check_cancel(is_cancelled)
        start_idx = int(round((e["at_ms"] / 1000.0) * sample_rate))
        if 0 <= start_idx < total_samples:
            _render_note(
                buf,
                start_idx=start_idx,
                pitch=int(e["mapped_pitch"]),
                velocity=96 if fixed_velocity else int(e["velocity"]),
                hold_ms=int(e["hold_ms"]),
                sample_rate=sample_rate,
            )

    _check_cancel(is_cancelled)
    peak = max((abs(x) for x in buf), default=0.0)
    scale = (_TARGET_PEAK / peak) if peak > 1e-9 else 1.0
    pcm = array.array("h", (max(-32767, min(32767, round(x * scale * 32767.0))) for x in buf))
    if sys.byteorder != "little":
        pcm.byteswap()

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return out.getvalue()


def synthesize_performance_to_wav(
    doc: Mapping[str, Any],
    out_path: str | Path,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    fixed_velocity: bool = False,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Render ``doc`` and atomically write the resulting WAV to ``out_path``."""
    wav_bytes = synthesize_performance(
        doc,
        sample_rate=sample_rate,
        fixed_velocity=fixed_velocity,
        is_cancelled=is_cancelled,
    )
    _check_cancel(is_cancelled)
    dest = Path(out_path)
    atomic_write_bytes(dest, wav_bytes)
    return dest
