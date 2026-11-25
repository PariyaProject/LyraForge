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
VALID_TIMBRES: tuple[str, ...] = ("auto", "piano", "lyre", "zither", "vintage")

_ATTACK_S = 0.005
_DECAY_RATE = 4.2
_TAIL_MIN_S = 0.45
_TAIL_MAX_S = 1.20
_END_PAD_S = 0.25
_TARGET_PEAK = 0.85


def resolve_timbre(profile_id: str | None = None, timbre: str = "auto") -> str:
    """Resolve and validate preview synthesis timbre from override or instrument profile."""
    clean = (timbre or "auto").strip().lower()
    if clean not in VALID_TIMBRES:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported preview timbre {timbre!r}; expected one of {', '.join(VALID_TIMBRES)}",
            {"timbre": timbre, "valid_timbres": list(VALID_TIMBRES)},
        )
    if clean != "auto":
        return clean
    pid = (profile_id or "").lower()
    if "harmonic_keys" in pid or "piano" in pid:
        return "piano"
    if "floral_zither" in pid or "zither" in pid:
        return "zither"
    if "vintage" in pid:
        return "vintage"
    return "lyre"


def _midi_pitch_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _timbre_envelope(hold_ms: int, pitch: int, timbre: str) -> tuple[float, float, float]:
    """Return ``(attack_s, decay_rate, note_dur_s)`` for the given timbre and pitch."""
    if timbre == "piano":
        pitch_norm = max(0.0, min(1.0, (pitch - 48) / 36.0))
        attack_s = 0.003
        decay_rate = 2.4 + 2.8 * pitch_norm
        note_dur_s = min(max(hold_ms / 1000.0 + 0.55, 0.70), 1.55)
        return attack_s, decay_rate, note_dur_s
    if timbre == "zither":
        return 0.0025, 3.2, min(max(hold_ms / 1000.0 + 0.45, 0.55), 1.35)
    if timbre == "vintage":
        return 0.008, 4.8, min(max(hold_ms / 1000.0 + 0.30, 0.40), 1.10)
    return _ATTACK_S, _DECAY_RATE, min(max(hold_ms / 1000.0 + 0.35, _TAIL_MIN_S), _TAIL_MAX_S)


def _render_note(
    buf: list[float],
    *,
    start_idx: int,
    pitch: int,
    velocity: int,
    hold_ms: int,
    sample_rate: int,
    timbre: str = "lyre",
) -> None:
    freq = _midi_pitch_to_hz(pitch)
    w = 2.0 * math.pi * freq / sample_rate
    attack_s, decay_rate, note_dur_s = _timbre_envelope(hold_ms, pitch, timbre)
    total_samples = max(1, int(round(note_dur_s * sample_rate)))
    attack_samples = max(1, int(round(attack_s * sample_rate)))
    amp = (velocity / 127.0) * 0.45
    limit = min(len(buf), start_idx + total_samples)
    fade_out_start = max(attack_samples, total_samples - int(round(0.04 * sample_rate)))

    for offset in range(limit - start_idx):
        t = offset / sample_rate
        if offset < attack_samples:
            env = offset / attack_samples
        else:
            env = math.exp(-decay_rate * (t - attack_s))
        if offset > fade_out_start and total_samples > fade_out_start:
            env *= (total_samples - offset) / (total_samples - fade_out_start)
        if timbre == "piano":
            hammer = 0.0
            if t < 0.008:
                hammer_w = min(0.45 * math.pi, w * 7.3)
                hammer = 0.16 * math.sin(hammer_w * offset) * math.exp(-t / 0.0025)
            wave_val = (
                math.sin(w * offset)
                + 0.46 * math.sin(2.0008 * w * offset) * math.exp(-3.5 * t)
                + 0.24 * math.sin(3.0 * w * offset) * math.exp(-6.5 * t)
                + 0.11 * math.sin(4.0 * w * offset) * math.exp(-10.0 * t)
                + 0.05 * math.sin(5.0 * w * offset) * math.exp(-14.0 * t)
                + hammer
            )
        elif timbre == "zither":
            wave_val = (
                math.sin(w * offset)
                + 0.42 * math.sin(2.0 * w * offset) * math.exp(-4.0 * t)
                + 0.28 * math.sin(3.0 * w * offset) * math.exp(-6.0 * t)
                + 0.16 * math.sin(4.0 * w * offset) * math.exp(-9.0 * t)
                + 0.09 * math.sin(5.0 * w * offset) * math.exp(-12.0 * t)
            )
        elif timbre == "vintage":
            wave_val = (
                math.sin(w * offset)
                + 0.20 * math.sin(2.0 * w * offset) * math.exp(-7.0 * t)
                + 0.05 * math.sin(3.0 * w * offset) * math.exp(-12.0 * t)
            )
        else:
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
    timbre: str = "auto",
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
    effective_timbre = resolve_timbre(
        str(doc.get("instrument_profile_id") or "") if isinstance(doc, Mapping) else None,
        timbre,
    )
    validate_performance(doc)

    events = doc["events"]
    max_end_s = max(
        (e["at_ms"] / 1000.0)
        + _timbre_envelope(int(e["hold_ms"]), int(e["mapped_pitch"]), effective_timbre)[2]
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
                timbre=effective_timbre,
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
    timbre: str = "auto",
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Render ``doc`` and atomically write the resulting WAV to ``out_path``."""
    wav_bytes = synthesize_performance(
        doc,
        sample_rate=sample_rate,
        fixed_velocity=fixed_velocity,
        timbre=timbre,
        is_cancelled=is_cancelled,
    )
    _check_cancel(is_cancelled)
    dest = Path(out_path)
    atomic_write_bytes(dest, wav_bytes)
    return dest
