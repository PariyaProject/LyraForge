"""Offline pure-tuned acoustic-inspired WAV preview synthesizer (pure stdlib).

Renders a validated ``performance.json`` to mono 16-bit PCM WAV using
phase-locked additive harmonics, pitch-balanced key voicing, same-pitch
retrigger damping, and a soft-knee chord limiter (no noisy reverb or
external sample assets).
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

_END_PAD_S = 0.25


def _midi_pitch_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


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


def _timbre_spec(
    hold_ms: int, pitch: int, timbre: str
) -> tuple[float, float, float, float, float, float, float, float, float, float]:
    """Return studio-voiced envelope and harmonic decay parameters for a timbre.

    Tuple fields:
      ``(attack_s, body_decay, note_dur_s, h2, h3, h4, h2_decay, h3_decay, h4_decay, bloom)``
    """
    hold_s = hold_ms / 1000.0
    pitch_norm = max(0.0, min(1.0, (pitch - 48) / 36.0))
    if timbre == "piano":
        # Clear singing studio piano: warm lower register, bell-clear upper octave, longer tail
        attack_s = 0.0035
        body_decay = 2.0 + 1.8 * pitch_norm
        note_dur_s = min(max(hold_s + 0.95, 1.30), 1.70)
        h2 = 0.42 - 0.14 * pitch_norm
        h3 = 0.18 - 0.08 * pitch_norm
        h4 = 0.07 - 0.04 * pitch_norm
        return attack_s, body_decay, note_dur_s, h2, h3, h4, 4.2, 7.6, 12.0, 0.24
    if timbre == "zither":
        # Silky Chinese plucked zither at exact fundamental pitch (warm midrange, quick shimmer)
        attack_s = 0.0025
        body_decay = 3.1 + 1.2 * pitch_norm
        note_dur_s = min(max(hold_s + 0.48, 0.78), 1.05)
        h2 = 0.46 - 0.14 * pitch_norm
        h3 = 0.22 - 0.08 * pitch_norm
        h4 = 0.10 - 0.05 * pitch_norm
        return attack_s, body_decay, note_dur_s, h2, h3, h4, 5.4, 9.2, 14.5, 0.28
    if timbre == "vintage":
        # Soft woody vintage harp with gentle attack and rounded treble
        attack_s = 0.0070
        body_decay = 4.0 + 1.0 * pitch_norm
        note_dur_s = min(max(hold_s + 0.42, 0.68), 0.95)
        h2 = 0.20 - 0.08 * pitch_norm
        h3 = 0.05
        h4 = 0.0
        return attack_s, body_decay, note_dur_s, h2, h3, h4, 5.8, 10.5, 14.0, 0.08
    # Default "lyre" — refined crystal plucked harp (smooth refinement of original Windsong Lyre)
    attack_s = 0.0045
    body_decay = 3.2 + 1.1 * pitch_norm
    note_dur_s = min(max(hold_s + 0.55, 0.85), 1.15)
    h2 = 0.36 - 0.10 * pitch_norm
    h3 = 0.14 - 0.05 * pitch_norm
    h4 = 0.04
    return attack_s, body_decay, note_dur_s, h2, h3, h4, 4.8, 8.8, 13.5, 0.16


def _render_note(
    buf: list[float],
    *,
    start_idx: int,
    pitch: int,
    velocity: int,
    hold_ms: int,
    sample_rate: int,
    timbre: str = "lyre",
    max_samples: int | None = None,
) -> None:
    (
        attack_s,
        body_decay,
        note_dur_s,
        h2,
        h3,
        h4,
        h2_decay,
        h3_decay,
        h4_decay,
        bloom,
    ) = _timbre_spec(hold_ms, pitch, timbre)

    total_samples = max(1, int(round(note_dur_s * sample_rate)))
    damped = max_samples is not None and max_samples < total_samples
    if max_samples is not None:
        total_samples = min(total_samples, max(1, max_samples))
    count = min(total_samples, len(buf) - start_idx)
    if count <= 0:
        return

    attack_samples = max(1, min(count, int(round(attack_s * sample_rate))))
    fade_s = 0.024 if damped else 0.055
    fade_out_len = min(count // 3, max(8, int(round(fade_s * sample_rate))))
    fade_out_start = count - fade_out_len

    # Subtle treble balance so low bass notes stay warm without muddying melody
    pitch_norm = max(0.0, min(1.0, (pitch - 48) / 36.0))
    pitch_level = 0.86 + 0.16 * pitch_norm
    harm_norm = 1.0 / (1.0 + 0.35 * h2 + 0.25 * h3 + 0.15 * h4)
    amp = (velocity / 127.0) * 0.44 * pitch_level * harm_norm

    w = 2.0 * math.pi * _midi_pitch_to_hz(pitch) / sample_rate
    cw = math.cos(w)
    sw = math.sin(w)

    # Anti-aliasing headroom for upper harmonics near Nyquist
    nyquist_lim = math.pi * 0.88
    if w * 2.0 > nyquist_lim:
        h2 = 0.0
    if w * 3.0 > nyquist_lim:
        h3 = 0.0
    if w * 4.0 > nyquist_lim:
        h4 = 0.0

    decay_step = 1.0 / sample_rate
    body_mul = math.exp(-body_decay * decay_step)
    bloom_mul = math.exp(-11.0 * decay_step)
    h2_mul = math.exp(-h2_decay * decay_step)
    h3_mul = math.exp(-h3_decay * decay_step)
    h4_mul = math.exp(-h4_decay * decay_step)

    c = 1.0
    s = 0.0
    env_body = 1.0
    env_bloom = 1.0
    e2 = 1.0
    e3 = 1.0
    e4 = 1.0

    pi = math.pi
    inv_att = pi / attack_samples
    inv_fade = pi / fade_out_len if fade_out_len > 0 else 0.0

    for offset in range(count):
        s2 = 2.0 * s * c
        c2 = c * c - s * s
        wave_val = s
        if h2 > 0.0:
            wave_val += (h2 * e2) * s2
        if h3 > 0.0:
            s3 = s2 * c + c2 * s
            wave_val += (h3 * e3) * s3
        if h4 > 0.0:
            s4 = 2.0 * s2 * c2
            wave_val += (h4 * e4) * s4

        if offset < attack_samples:
            att = 0.5 * (1.0 - math.cos(offset * inv_att))
            env = att * (1.0 + bloom * env_bloom)
        else:
            env = env_body * (1.0 + bloom * env_bloom)
            env_body *= body_mul

        if offset >= fade_out_start and fade_out_len > 0:
            fade_pos = offset - fade_out_start
            env *= 0.5 * (1.0 + math.cos(fade_pos * inv_fade))

        buf[start_idx + offset] += amp * env * wave_val

        # Advance fundamental oscillator phase & decay envelopes
        next_c = c * cw - s * sw
        next_s = s * cw + c * sw
        if (offset & 511) == 511:
            norm = math.hypot(next_c, next_s) or 1.0
            c = next_c / norm
            s = next_s / norm
        else:
            c = next_c
            s = next_s
        env_bloom *= bloom_mul
        e2 *= h2_mul
        e3 *= h3_mul
        e4 *= h4_mul


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
        + max(
            int(e.get("hold_ms", 40)) / 1000.0,
            _timbre_spec(
                int(e.get("hold_ms", 40)), int(e["mapped_pitch"]), effective_timbre
            )[2],
        )
        for e in events
    )
    total_samples = max(1, int(math.ceil((max_end_s + _END_PAD_S) * sample_rate)))
    buf = [0.0] * total_samples

    # Damp an active note cleanly before the exact same pitch re-strikes so rapid runs
    # sound crisp without accumulation or comb-filtering while distinct chord notes ring freely.
    next_at_by_pitch: dict[int, int] = {}
    same_pitch_caps: list[int | None] = [None] * len(events)
    min_cap_samples = max(16, int(round(0.025 * sample_rate)))
    for idx in range(len(events) - 1, -1, -1):
        pitch = int(events[idx]["mapped_pitch"])
        at_ms = int(events[idx]["at_ms"])
        nxt = next_at_by_pitch.get(pitch)
        if nxt is not None and nxt > at_ms:
            gap_s = (nxt - at_ms) / 1000.0 + 0.004
            same_pitch_caps[idx] = max(min_cap_samples, int(round(gap_s * sample_rate)))
        next_at_by_pitch[pitch] = at_ms

    for idx, e in enumerate(events):
        _check_cancel(is_cancelled)
        start_idx = int(round((e["at_ms"] / 1000.0) * sample_rate))
        if 0 <= start_idx < total_samples:
            _render_note(
                buf,
                start_idx=start_idx,
                pitch=int(e["mapped_pitch"]),
                velocity=96 if fixed_velocity else int(e.get("velocity", 96)),
                hold_ms=int(e.get("hold_ms", 40)),
                sample_rate=sample_rate,
                timbre=effective_timbre,
                max_samples=same_pitch_caps[idx],
            )

    _check_cancel(is_cancelled)
    peak = max((abs(x) for x in buf), default=0.0)
    if peak > 1e-9:
        rms = math.sqrt(sum(x * x for x in buf) / len(buf))
        gain = min(2.0, max(0.65, 0.16 / max(rms, 1e-4)))
        if peak * gain <= 0.88:
            pcm = array.array(
                "h",
                (max(-32767, min(32767, round(x * gain * 32767.0))) for x in buf),
            )
        else:
            knee = 0.72
            headroom = 0.20

            def _soft_limit(val: float) -> int:
                y = val * gain
                ay = abs(y)
                if ay > knee:
                    limited = knee + headroom * math.tanh((ay - knee) / headroom)
                    y = limited if y >= 0.0 else -limited
                return max(-32767, min(32767, round(y * 32767.0)))

            pcm = array.array("h", (_soft_limit(x) for x in buf))
    else:
        pcm = array.array("h", [0] * len(buf))

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
