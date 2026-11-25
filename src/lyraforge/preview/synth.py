"""Offline acoustic & plucked-lyre WAV preview synthesizer (pure cross-platform stdlib).

Renders a validated ``performance.json`` to mono 16-bit PCM WAV using bundled
CC0-1.0 Versilian Community Sample Library (VCSL) acoustic recordings
(Steinway Model B grand piano, Concert Harp, and Dan Tranh zither) with a
soft-knee chord master stage and zero external audio dependencies.
"""

from __future__ import annotations

import array
import io
import json
import math
import sys
import wave
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes
from lyraforge.music_core.performance import validate_performance

DEFAULT_SAMPLE_RATE = 22_050
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 48_000
VALID_TIMBRES: tuple[str, ...] = ("auto", "piano", "lyre", "zither", "vintage")

_ATTACK_S = 0.004
_DECAY_RATE = 4.2
_TAIL_MIN_S = 0.45
_TAIL_MAX_S = 1.20
_END_PAD_S = 0.25


def resolve_samples_dir() -> Path:
    """Locate bundled CC0 acoustic sample assets in source or PyInstaller bundle."""
    local = Path(__file__).resolve().parent / "samples"
    if (local / "manifest.json").is_file():
        return local
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "lyraforge" / "preview" / "samples"
        if (bundled / "manifest.json").is_file():
            return bundled
    return local


@lru_cache(maxsize=1)
def load_sample_manifest() -> dict[str, Any]:
    """Load and validate the bundled CC0 sample pack manifest."""
    manifest_path = resolve_samples_dir() / "manifest.json"
    if not manifest_path.is_file():
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "bundled preview sample manifest is missing",
            {"path": str(manifest_path)},
        )
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"failed to read preview sample manifest: {exc}",
        ) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("packs"), dict):
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "bundled preview sample manifest has invalid schema",
        )
    return doc


def get_sample_file_path(pack: str, filename: str) -> Path:
    """Strictly resolve an allowlisted CC0 sample WAV path from manifest.json."""
    clean_pack = (pack or "").strip().lower()
    clean_name = (filename or "").strip()
    if (
        not clean_pack
        or not clean_name
        or "/" in clean_name
        or "\\" in clean_name
        or ".." in clean_name
        or "\x00" in clean_name
    ):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"invalid preview sample path: {pack}/{filename}",
            {"pack": pack, "filename": filename},
        )
    manifest = load_sample_manifest()
    entries = manifest.get("packs", {}).get(clean_pack)
    if not isinstance(entries, list):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown preview sample pack: {pack!r}",
            {"pack": pack, "available_packs": sorted(manifest.get("packs", {}))},
        )
    expected_rel = f"{clean_pack}/{clean_name}"
    matched = next(
        (e for e in entries if isinstance(e, dict) and e.get("file") == expected_rel),
        None,
    )
    if matched is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown preview sample file: {expected_rel}",
            {"pack": clean_pack, "filename": clean_name},
        )
    sample_path = (resolve_samples_dir() / expected_rel).resolve()
    samples_root = resolve_samples_dir().resolve()
    if not sample_path.is_relative_to(samples_root) or not sample_path.is_file():
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"preview sample file missing on disk: {expected_rel}",
        )
    return sample_path


@lru_cache(maxsize=4)
def _load_pack_samples(pack: str) -> tuple[tuple[int, int, tuple[float, ...]], ...]:
    manifest_path = resolve_samples_dir() / "manifest.json"
    if not manifest_path.is_file():
        return ()
    manifest = load_sample_manifest()
    entries = manifest.get("packs", {}).get(pack)
    if not isinstance(entries, list):
        return ()
    loaded: list[tuple[int, int, tuple[float, ...]]] = []
    for entry in entries:
        if not isinstance(entry, dict) or "file" not in entry or "pitch" not in entry:
            continue
        filename = Path(str(entry["file"])).name
        wav_path = get_sample_file_path(pack, filename)
        with wave.open(str(wav_path), "rb") as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sw != 2 or ch < 1:
            continue
        arr = array.array("h")
        arr.frombytes(raw)
        if sys.byteorder != "little":
            arr.byteswap()
        if ch == 1:
            floats = tuple(s / 32768.0 for s in arr)
        else:
            floats = tuple(
                sum(arr[i : i + ch]) / (ch * 32768.0) for i in range(0, len(arr) - ch + 1, ch)
            )
        loaded.append((int(entry["pitch"]), int(sr), floats))
    loaded.sort(key=lambda item: item[0])
    return tuple(loaded)


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


def _pack_for_timbre(timbre: str) -> str:
    if timbre == "piano":
        return "piano"
    if timbre == "zither":
        return "zither"
    return "lyre"


def _midi_pitch_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def _timbre_envelope(hold_ms: int, pitch: int, timbre: str) -> tuple[float, float, float]:
    """Return ``(attack_s, decay_rate, note_dur_s)`` for fallback or tail estimation."""
    hold_s = hold_ms / 1000.0
    if timbre == "piano":
        pitch_norm = max(0.0, min(1.0, (pitch - 48) / 36.0))
        attack_s = 0.0025
        decay_rate = 2.2 + 2.5 * pitch_norm
        note_dur_s = min(max(hold_s + 1.05, 1.35), 1.80)
        return attack_s, decay_rate, note_dur_s
    if timbre == "zither":
        return 0.002, 3.2, min(max(hold_s + 0.65, 0.95), 1.30)
    if timbre == "vintage":
        return 0.006, 4.4, min(max(hold_s + 0.70, 0.95), 1.40)
    return _ATTACK_S, _DECAY_RATE, min(max(hold_s + 0.85, 1.15), 1.60)


def _render_sampled_note(
    buf: list[float],
    *,
    start_idx: int,
    pitch: int,
    velocity: int,
    hold_ms: int,
    sample_rate: int,
    timbre: str,
    pack_samples: tuple[tuple[int, int, tuple[float, ...]], ...],
    max_samples: int | None = None,
) -> bool:
    if not pack_samples:
        return False
    anchor_pitch, src_sr, src_pcm = min(
        pack_samples, key=lambda item: (abs(item[0] - pitch), abs(item[0]))
    )
    n_src = len(src_pcm)
    if n_src < 8:
        return False

    step = (src_sr / sample_rate) * (2.0 ** ((pitch - anchor_pitch) / 12.0))
    if step <= 0.0:
        return False

    _, _, target_dur_s = _timbre_envelope(hold_ms, pitch, timbre)
    max_src_samples = int((n_src - 2) / step)
    total_samples = min(max_src_samples, max(1, int(round(target_dur_s * sample_rate))))
    damped = max_samples is not None and max_samples < total_samples
    if max_samples is not None:
        total_samples = min(total_samples, max(1, max_samples))
    if total_samples <= 0 or start_idx >= len(buf):
        return True

    count = min(total_samples, len(buf) - start_idx)
    amp = (velocity / 127.0) * 0.48
    fade_s = 0.024 if damped else 0.080
    fade_out_len = min(count // 3, max(16, int(round(fade_s * sample_rate))))
    main_end = count - fade_out_len
    exact_step = abs(step - 1.0) < 1e-6

    if timbre == "vintage":
        lp = 0.0
        alpha = 0.34
        pos = 0.0
        for offset in range(count):
            if exact_step:
                raw_val = src_pcm[offset]
            else:
                i0 = int(pos)
                frac = pos - i0
                raw_val = src_pcm[i0] + frac * (src_pcm[i0 + 1] - src_pcm[i0])
                pos += step
            lp += alpha * (raw_val - lp)
            env = amp
            if offset >= main_end:
                env *= (count - offset) / fade_out_len
            buf[start_idx + offset] += lp * env
        return True

    if exact_step:
        for offset in range(main_end):
            buf[start_idx + offset] += src_pcm[offset] * amp
        for offset in range(main_end, count):
            env = amp * (count - offset) / fade_out_len
            buf[start_idx + offset] += src_pcm[offset] * env
        return True

    pos = 0.0
    for offset in range(main_end):
        i0 = int(pos)
        sample = src_pcm[i0] + (pos - i0) * (src_pcm[i0 + 1] - src_pcm[i0])
        buf[start_idx + offset] += sample * amp
        pos += step
    for offset in range(main_end, count):
        i0 = int(pos)
        sample = src_pcm[i0] + (pos - i0) * (src_pcm[i0 + 1] - src_pcm[i0])
        buf[start_idx + offset] += sample * (amp * (count - offset) / fade_out_len)
        pos += step
    return True


def _render_fallback_note(
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
    note_dur_s = min(note_dur_s, _TAIL_MAX_S)
    total_samples = max(1, int(round(note_dur_s * sample_rate)))
    attack_samples = max(1, int(round(attack_s * sample_rate)))
    amp = (velocity / 127.0) * 0.42
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
        wave_val = (
            math.sin(w * offset)
            + 0.35 * math.sin(2.0 * w * offset) * math.exp(-5.0 * t)
            + 0.14 * math.sin(3.0 * w * offset) * math.exp(-9.0 * t)
        )
        buf[start_idx + offset] += amp * env * wave_val


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
    pack_samples = _load_pack_samples(_pack_for_timbre(timbre))
    used_real = _render_sampled_note(
        buf,
        start_idx=start_idx,
        pitch=pitch,
        velocity=velocity,
        hold_ms=hold_ms,
        sample_rate=sample_rate,
        timbre=timbre,
        pack_samples=pack_samples,
        max_samples=max_samples,
    )
    if not used_real:
        _render_fallback_note(
            buf,
            start_idx=start_idx,
            pitch=pitch,
            velocity=velocity,
            hold_ms=hold_ms,
            sample_rate=sample_rate,
            timbre=timbre,
        )


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
            _timbre_envelope(
                int(e.get("hold_ms", 40)), int(e["mapped_pitch"]), effective_timbre
            )[2],
        )
        for e in events
    )
    total_samples = max(1, int(math.ceil((max_end_s + _END_PAD_S) * sample_rate)))
    buf = [0.0] * total_samples

    # Damp an active note slightly before the exact same pitch re-strikes so repeated
    # notes do not accumulate or comb-filter while distinct pitches ring freely together.
    next_at_by_pitch: dict[int, int] = {}
    same_pitch_caps: list[int | None] = [None] * len(events)
    min_cap_samples = max(16, int(round(0.025 * sample_rate)))
    for idx in range(len(events) - 1, -1, -1):
        pitch = int(events[idx]["mapped_pitch"])
        at_ms = int(events[idx]["at_ms"])
        nxt = next_at_by_pitch.get(pitch)
        if nxt is not None and nxt > at_ms:
            gap_s = (nxt - at_ms) / 1000.0 + 0.006
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
        gain = min(2.2, max(0.75, 0.16 / max(rms, 1e-4)))
        if peak * gain <= 0.88:
            pcm = array.array(
                "h",
                (max(-32767, min(32767, round(x * gain * 32767.0))) for x in buf),
            )
        else:
            knee = 0.68
            headroom = 0.24

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
