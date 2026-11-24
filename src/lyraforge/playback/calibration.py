"""Instrument playback benchmark & calibration suite (patterns A-G + WAV onset analysis).

Tiers supported cleanly without misclaiming acoustic truth:
1. ``dry_run_virtual``   — VirtualClock deterministic timing / retrigger verification.
2. ``realtime_scheduler``— MonotonicClock real-time scheduler & jitter measurement.
3. ``in_game_prepare``   — User-authorized live Windows playback via standard two-step guard
                           (handled by ``PlaybackManager.prepare_events``), paired with
                           ``analyze_calibration_recording`` for game-audio onset measurement.

Never reports DryRun or SendInput success as confirmed in-game audio emission.
"""

from __future__ import annotations

import hashlib
import io
import math
import statistics
import struct
import time
import uuid
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyraforge import __version__
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.canonical import canonical_json_bytes
from lyraforge.music_core.performance import SCHEMA_VERSION, validate_performance
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.playback.clock import MonotonicClock, VirtualClock
from lyraforge.playback.driver import DryRunDriver
from lyraforge.playback.player import LateEventPolicy, PlaybackOptions, Player

_CALIBRATION_NS = uuid.UUID("7249b940-8b2f-5c9b-9b4a-5b09f34b8011")


@dataclass(frozen=True, slots=True)
class CalibrationPattern:
    id: str
    code: str
    display_name: str
    description: str
    default_duration_s: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "display_name": self.display_name,
            "description": self.description,
            "default_duration_s": self.default_duration_s,
        }


CALIBRATION_PATTERNS: dict[str, CalibrationPattern] = {
    "distinct_key_rapid": CalibrationPattern(
        id="distinct_key_rapid",
        code="A",
        display_name="A · 不同琴键连续触发（5–100 ms 阶梯）",
        description=(
            "依次以 100/75/50/40/30/20/15/10/5 ms 间隔连续敲击相邻琴键，"
            "检测异键最小可靠起音间隔。"
        ),
    ),
    "same_key_retrigger": CalibrationPattern(
        id="same_key_retrigger",
        code="B",
        display_name="B · 同键重复触发（30–150 ms 阶梯）",
        description="对单键中音 1（mid_1）以 150 → 30 ms 递减间隔连击，检验同键最小可重触发周期。",
    ),
    "chord_simultaneous": CalibrationPattern(
        id="chord_simultaneous",
        code="C",
        display_name="C · 多键同时触发（2–6 音和弦）",
        description="以 500 ms 步进依次发送 2、3、4、5、6 键同步和弦，测量最大可靠和弦复音密度。",
    ),
    "rapid_arpeggio": CalibrationPattern(
        id="rapid_arpeggio",
        code="D",
        display_name="D · 快速上下行琶音（10–50 ms 音序）",
        description="验证 50 / 30 / 20 / 15 / 10 ms 间隔六音上行与下行琶音顺序保真度与吞音阈值。",
    ),
    "hold_release_sweep": CalibrationPattern(
        id="hold_release_sweep",
        code="E",
        display_name="E · 按键保持与释放间隔扫描",
        description=(
            "扫描不同 (hold_ms, release_gap_ms) 组合，"
            "确定最低可触发按住时长与释放恢复窗口。"
        ),
    ),
    "long_stability": CalibrationPattern(
        id="long_stability",
        code="F",
        display_name="F · 长时稳态与抖动基准",
        description=(
            "持续运行混合脉冲、和弦与快速琶音，"
            "统计 P50/P95/P99 延迟、累计漂移与 CPU 占用率。"
        ),
        default_duration_s=10.0,
    ),
    "instrument_sustain_trigger": CalibrationPattern(
        id="instrument_sustain_trigger",
        code="G",
        display_name="G · 乐器余音与触发机制对比（短按 vs 长按）",
        description=(
            "在低/中/高三音区交替执行 20 ms 短按与 350 ms 长按，"
            "结合录音判断 one_shot 还是 sustained。"
        ),
    ),
}


def list_calibration_patterns() -> list[dict[str, Any]]:
    return [p.to_json() for p in CALIBRATION_PATTERNS.values()]


def get_calibration_pattern(pattern_id: str) -> CalibrationPattern:
    pat = CALIBRATION_PATTERNS.get(pattern_id)
    if pat is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown calibration pattern: {pattern_id!r}",
            {"available": list(CALIBRATION_PATTERNS)},
        )
    return pat


def _pick_key(profile: InstrumentProfile, preferred_id: str, fallback_idx: int) -> Any:
    k = profile.key_by_id(preferred_id)
    if k is not None:
        return k
    ordered = sorted(profile.keys, key=lambda item: item.pitch)
    return ordered[min(max(0, fallback_idx), len(ordered) - 1)]


def _make_event(at_ms: int, key_def: Any, hold_ms: int) -> dict[str, Any]:
    return {
        "at_ms": int(at_ms),
        "key_id": key_def.key_id,
        "action": "tap",
        "hold_ms": int(max(1, hold_ms)),
        "source_pitch": int(key_def.pitch),
        "mapped_pitch": int(key_def.pitch),
        "source_track": 0,
        "source_channel": 0,
        "velocity": 100,
        "adjustments": [],
    }


def build_calibration_performance(
    pattern_id: str,
    profile: InstrumentProfile,
    *,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Generate a deterministic, schema-validated calibration ``performance.json`` + segments."""
    pat = get_calibration_pattern(pattern_id)
    ordered_keys = sorted(profile.keys, key=lambda item: item.pitch)
    # Use middle register keys (mid_1..mid_7) when available
    mid_base = min(7, max(0, len(ordered_keys) - 7))
    ring_keys = ordered_keys[mid_base : mid_base + 7]
    if len(ring_keys) < 6:
        ring_keys = ordered_keys

    events: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    t_ms = 0

    if pattern_id == "distinct_key_rapid":
        intervals = [100, 75, 50, 40, 30, 20, 15, 10, 5]
        for idx, gap in enumerate(intervals):
            seg_start = t_ms
            seg_events: list[dict[str, Any]] = []
            hold = min(20, max(5, gap - 3))
            for step in range(4):
                ev = _make_event(t_ms, ring_keys[step % len(ring_keys)], hold)
                events.append(ev)
                seg_events.append(ev)
                t_ms += gap
            segments.append({
                "index": idx,
                "label": f"{gap}ms",
                "interval_ms": gap,
                "start_ms": seg_start,
                "end_ms": t_ms,
                "expected_count": len(seg_events),
                "chord_sizes": [1] * len(seg_events),
            })
            t_ms += 350

    elif pattern_id == "same_key_retrigger":
        k = _pick_key(profile, "mid_1", len(ordered_keys) // 2)
        intervals = [150, 120, 100, 80, 60, 50, 40, 30]
        for idx, gap in enumerate(intervals):
            seg_start = t_ms
            hold = min(25, max(10, gap - 15))
            for _ in range(4):
                events.append(_make_event(t_ms, k, hold))
                t_ms += gap
            segments.append({
                "index": idx,
                "label": f"{gap}ms",
                "interval_ms": gap,
                "hold_ms": hold,
                "release_gap_ms": gap - hold,
                "start_ms": seg_start,
                "end_ms": t_ms,
                "expected_count": 4,
            })
            t_ms += 350

    elif pattern_id == "chord_simultaneous":
        chord_pool = [
            _pick_key(profile, "low_1", 0),
            _pick_key(profile, "low_5", 4),
            _pick_key(profile, "mid_1", 7),
            _pick_key(profile, "mid_3", 9),
            _pick_key(profile, "mid_5", 11),
            _pick_key(profile, "high_1", 14),
        ]
        # Deduplicate while preserving spread
        unique_pool = list(dict.fromkeys(chord_pool))
        for idx, size in enumerate([2, 3, 4, 5, 6]):
            actual_size = min(size, len(unique_pool))
            seg_start = t_ms
            for k in unique_pool[:actual_size]:
                events.append(_make_event(t_ms, k, 50))
            segments.append({
                "index": idx,
                "label": f"{actual_size}-key chord",
                "chord_size": actual_size,
                "start_ms": seg_start,
                "end_ms": t_ms + 50,
                "expected_count": actual_size,
            })
            t_ms += 500

    elif pattern_id == "rapid_arpeggio":
        arp_keys = ring_keys[: min(6, len(ring_keys))]
        intervals = [50, 30, 20, 15, 10]
        for gap in intervals:
            for direction, seq_keys in (("asc", arp_keys), ("desc", list(reversed(arp_keys)))):
                seg_start = t_ms
                hold = min(25, max(8, gap))
                for k in seq_keys:
                    events.append(_make_event(t_ms, k, hold))
                    t_ms += gap
                segments.append({
                    "index": len(segments),
                    "label": f"{direction} {gap}ms",
                    "direction": direction,
                    "interval_ms": gap,
                    "start_ms": seg_start,
                    "end_ms": t_ms,
                    "expected_count": len(seq_keys),
                })
                t_ms += 400

    elif pattern_id == "hold_release_sweep":
        k = _pick_key(profile, "mid_1", len(ordered_keys) // 2)
        pairs = [(15, 10), (15, 20), (25, 15), (25, 20), (40, 20), (40, 30), (80, 20)]
        for idx, (hold_ms, rel_gap_ms) in enumerate(pairs):
            seg_start = t_ms
            step = hold_ms + rel_gap_ms
            for _ in range(3):
                events.append(_make_event(t_ms, k, hold_ms))
                t_ms += step
            segments.append({
                "index": idx,
                "label": f"hold={hold_ms}ms gap={rel_gap_ms}ms",
                "hold_ms": hold_ms,
                "release_gap_ms": rel_gap_ms,
                "interval_ms": step,
                "start_ms": seg_start,
                "end_ms": t_ms,
                "expected_count": 3,
            })
            t_ms += 350

    elif pattern_id == "long_stability":
        raw_dur = max(1.0, min(180.0, float(duration_s or pat.default_duration_s or 10.0)))
        target_dur_ms = int(round(raw_dur * 1000))
        pulse_step = 125
        idx = 0
        while t_ms + 80 <= target_dur_ms:
            if idx % 16 == 8 and len(ring_keys) >= 6:
                # Rapid 25ms 4-note arpeggio burst
                for j in range(4):
                    events.append(_make_event(t_ms + j * 25, ring_keys[j], 20))
            elif idx % 8 == 4 and len(ring_keys) >= 5:
                # 3-note simultaneous chord
                for k_idx in (0, 2, 4):
                    events.append(_make_event(t_ms, ring_keys[k_idx], 40))
            else:
                events.append(_make_event(t_ms, ring_keys[idx % len(ring_keys)], 30))
            t_ms += pulse_step
            idx += 1
        segments.append({
            "index": 0,
            "label": f"stability {target_dur_ms / 1000:.1f}s",
            "interval_ms": pulse_step,
            "start_ms": 0,
            "end_ms": t_ms,
            "expected_count": len(events),
        })

    elif pattern_id == "instrument_sustain_trigger":
        probes = [
            (_pick_key(profile, "low_1", 0), 20, "low_short"),
            (_pick_key(profile, "low_1", 0), 350, "low_long"),
            (_pick_key(profile, "mid_1", 7), 20, "mid_short"),
            (_pick_key(profile, "mid_1", 7), 350, "mid_long"),
            (_pick_key(profile, "high_1", 14), 20, "high_short"),
            (_pick_key(profile, "high_1", 14), 350, "high_long"),
        ]
        for idx, (k, hold_ms, label) in enumerate(probes):
            events.append(_make_event(t_ms, k, hold_ms))
            segments.append({
                "index": idx,
                "label": label,
                "key_id": k.key_id,
                "hold_ms": hold_ms,
                "start_ms": t_ms,
                "end_ms": t_ms + hold_ms,
                "expected_count": 1,
            })
            t_ms += 1600

    duration_ms = max(e["at_ms"] + e["hold_ms"] for e in events)
    song_id = str(uuid.uuid5(_CALIBRATION_NS, f"song:{profile.id}:{pattern_id}"))
    arr_digest = hashlib.sha256(
        canonical_json_bytes({"profile": profile.hash, "pattern": pattern_id, "events": events})
    ).hexdigest()
    arr_id = str(uuid.uuid5(_CALIBRATION_NS, f"arr:{arr_digest}"))
    perf_doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "lyraforge.performance",
        "song_id": song_id,
        "arrangement_id": arr_id,
        "instrument_profile_id": profile.id,
        "instrument_profile_hash": profile.hash,
        "tempo_map": [{"tick": 0, "at_ms": 0, "us_per_beat": 500_000, "bpm": 120.0}],
        "duration_ms": duration_ms,
        "events": events,
        "transform": {
            "strategy": "balanced",
            "transpose_semitones": 0,
            "speed": 1.0,
        },
        "provenance": {
            "input_sha256": arr_digest,
            "transcriber": "calibration",
            "arranger_version": __version__,
        },
    }
    validate_performance(perf_doc, profile)
    return {
        "pattern": pat.to_json(),
        "performance": perf_doc,
        "segments": segments,
    }


def _check_log_ordering_and_gaps(log_entries: Sequence[Any]) -> dict[str, Any]:
    downs = [e for e in log_entries if e.action == "down"]
    down_keys = [e.key_id for e in downs]
    last_up: dict[str, int] = {}
    min_rel_gap_us: int | None = None
    overlapping_down = 0
    pressed_sim: set[str] = set()
    for e in log_entries:
        if e.action == "down":
            if e.key_id in pressed_sim:
                overlapping_down += 1
            pressed_sim.add(e.key_id)
            if e.key_id in last_up:
                gap = e.t_us - last_up[e.key_id]
                if min_rel_gap_us is None or gap < min_rel_gap_us:
                    min_rel_gap_us = gap
        elif e.action in {"up", "release"}:
            pressed_sim.discard(e.key_id)
            last_up[e.key_id] = e.t_us
    return {
        "down_count": len(downs),
        "first_12_keys": down_keys[:12],
        "overlapping_key_downs": overlapping_down,
        "min_observed_release_gap_ms": (
            round(min_rel_gap_us / 1000.0, 3) if min_rel_gap_us is not None else None
        ),
    }


def run_calibration_benchmark(
    pattern_id: str,
    profile: InstrumentProfile,
    *,
    realtime: bool = False,
    playback_options: PlaybackOptions | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Execute Tier 1 (virtual) or Tier 2 (realtime MonotonicClock) benchmark."""
    built = build_calibration_performance(pattern_id, profile, duration_s=duration_s)
    perf_doc = built["performance"]
    events = perf_doc["events"]

    rel_gap = (
        0
        if pattern_id == "hold_release_sweep"
        else profile.timing.min_key_release_gap_ms
    )
    opts = playback_options or PlaybackOptions(
        min_key_release_gap_ms=rel_gap,
        late_event_policy=LateEventPolicy.SHIFT_CLOCK,
        record_trace=True,
    )
    clock: Any = MonotonicClock() if realtime else VirtualClock()
    driver = DryRunDriver(clock)
    player = Player(driver, clock, options=opts)

    cpu0 = time.process_time()
    result = player.play(events)
    cpu1 = time.process_time()

    wall_ms = round((result.ended_at_us - result.started_at_us) / 1000.0, 3)
    expected_dur_ms = int(perf_doc["duration_ms"])
    drift_ms = round(wall_ms - expected_dur_ms, 3)
    cpu_pct = round(((cpu1 - cpu0) * 1000.0 / wall_ms) * 100.0, 2) if wall_ms > 0 else 0.0
    log_stats = _check_log_ordering_and_gaps(driver.log)

    return {
        "tier": "realtime_scheduler" if realtime else "dry_run_virtual",
        "verifies_game_audio": False,
        "notice": (
            "Dry-Run / 调度基准仅验证 lyraforge 事件时间轴、不重叠释放与本地计时抖动，"
            "不能替代 Windows 下《原神》实机发声校准。"
        ),
        "pattern": built["pattern"],
        "instrument_profile_id": profile.id,
        "timing_profile": {
            "min_same_key_interval_ms": profile.timing.min_same_key_interval_ms,
            "min_key_hold_ms": profile.timing.min_key_hold_ms,
            "default_key_hold_ms": profile.timing.default_key_hold_ms,
            "max_key_hold_ms": profile.timing.max_key_hold_ms,
            "min_key_release_gap_ms": profile.timing.min_key_release_gap_ms,
            "min_inter_key_interval_ms": profile.timing.min_inter_key_interval_ms,
            "trigger_mode": profile.timing.trigger_mode,
            "provisional": profile.timing.provisional,
        },
        "expected_events": len(events),
        "expected_duration_ms": expected_dur_ms,
        "actual_elapsed_ms": wall_ms,
        "drift_ms": drift_ms,
        "cpu_pct": cpu_pct,
        "result": result.to_json(),
        "log_verification": log_stats,
        "segments": built["segments"],
    }


def _decode_wav_mono(raw_bytes: bytes) -> tuple[list[float], int]:
    try:
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            nframes = wf.getnframes()
            frames = wf.readframes(nframes)
    except Exception as exc:
        raise LyraError(
            ErrorCode.MEDIA_DECODE_FAILED,
            f"failed to decode WAV recording: {type(exc).__name__}: {exc}",
        ) from exc
    if channels <= 0 or sr <= 0 or nframes <= 0 or sampwidth not in {1, 2, 3, 4}:
        raise LyraError(
            ErrorCode.MEDIA_DECODE_FAILED,
            "recording WAV must be non-empty PCM (8/16/24/32-bit)",
        )

    samples: list[float] = []
    if sampwidth == 1:
        raw_vals = [(b - 128) / 128.0 for b in frames]
    elif sampwidth == 2:
        count = len(frames) // 2
        raw_vals = [v / 32768.0 for v in struct.unpack(f"<{count}h", frames)]
    elif sampwidth == 3:
        raw_vals = []
        for idx in range(0, len(frames) - 2, 3):
            b0, b1, b2 = frames[idx], frames[idx + 1], frames[idx + 2]
            val = b0 | (b1 << 8) | (b2 << 16)
            if val & 0x800000:
                val -= 0x1000000
            raw_vals.append(val / 8388608.0)
    else:
        count = len(frames) // 4
        raw_vals = [v / 2147483648.0 for v in struct.unpack(f"<{count}i", frames)]

    if channels == 1:
        samples = raw_vals
    else:
        for i in range(0, len(raw_vals) - channels + 1, channels):
            samples.append(sum(raw_vals[i : i + channels]) / channels)
    return samples, sr


def _detect_onsets_from_envelope(
    samples: Sequence[float],
    sample_rate: int,
    *,
    hop_ms: float = 5.0,
    min_peak_sep_ms: float = 9.0,
) -> tuple[list[float], list[float], list[float], float]:
    hop = max(1, int(round(sample_rate * hop_ms / 1000.0)))
    win = max(hop, int(round(sample_rate * 0.010)))
    rms: list[float] = []
    n = len(samples)
    pos = 0
    while pos < n:
        end = min(n, pos + win)
        chunk = samples[pos:end]
        mean_sq = sum(x * x for x in chunk) / max(1, len(chunk))
        rms.append(math.sqrt(mean_sq))
        pos += hop

    if not rms:
        return [], [], [], 0.0

    sorted_rms = sorted(rms)
    noise_floor = sorted_rms[min(len(sorted_rms) - 1, max(0, len(sorted_rms) // 4))]
    flux = [max(0.0, rms[0] - noise_floor)]
    for i in range(1, len(rms)):
        # Require actual positive attack slope; decay (~0.91/hop) stays <= 0.98 * rms[i-1]
        flux.append(max(0.0, rms[i] - 0.98 * rms[i - 1]))

    med_flux = statistics.median(flux)
    mad_flux = statistics.median([abs(x - med_flux) for x in flux])
    threshold = max(noise_floor * 2.2, med_flux + max(0.008, mad_flux * 4.0))

    min_sep_frames = max(1, int(round(min_peak_sep_ms / hop_ms)))
    onset_times_ms: list[float] = []
    last_peak_idx = -min_sep_frames - 1
    for i in range(len(flux)):
        if flux[i] < threshold or rms[i] < noise_floor * 2.0:
            continue
        prev_v = flux[i - 1] if i > 0 else 0.0
        next_v = flux[i + 1] if i + 1 < len(flux) else 0.0
        if flux[i] >= prev_v and flux[i] >= next_v:
            if i - last_peak_idx >= min_sep_frames:
                onset_times_ms.append(i * hop_ms)
                last_peak_idx = i
            elif onset_times_ms and flux[i] > flux[last_peak_idx]:
                onset_times_ms[-1] = i * hop_ms
                last_peak_idx = i
    return onset_times_ms, rms, flux, noise_floor


def _cluster_expected_onsets(
    expected_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    ordered = sorted(expected_events, key=lambda e: int(e["at_ms"]))
    for ev in ordered:
        at_ms = int(ev["at_ms"])
        if clusters and abs(at_ms - clusters[-1]["at_ms"]) <= 4:
            clusters[-1]["events"].append(ev)
        else:
            clusters.append({"at_ms": at_ms, "events": [ev]})
    return clusters


def _estimate_global_offset_ms(
    expected_ms: Sequence[float],
    detected_ms: Sequence[float],
    *,
    tolerance_ms: float,
) -> float:
    if not expected_ms or not detected_ms:
        return 0.0
    candidates: set[float] = {0.0}
    e0 = expected_ms[0]
    for det in detected_ms[:5]:
        candidates.add(round(det - e0, 1))
    # Also scan coarse-to-fine grid around common recording start lags (-3000..+5000ms)
    step = 25.0
    off = -3000.0
    while off <= 5000.0:
        candidates.add(off)
        off += step

    def _score_offset(offset: float) -> tuple[int, float]:
        hits = 0
        sq_err = 0.0
        j = 0
        for exp in expected_ms:
            target = exp + offset
            while j < len(detected_ms) and detected_ms[j] < target - tolerance_ms:
                j += 1
            if j < len(detected_ms) and abs(detected_ms[j] - target) <= tolerance_ms:
                hits += 1
                err = detected_ms[j] - target
                sq_err += err * err
                j += 1
        return hits, -sq_err

    best_coarse = max(candidates, key=_score_offset)
    fine_best = best_coarse
    fine_score = _score_offset(best_coarse)
    for delta in range(-25, 26, 2):
        cand = round(best_coarse + delta, 1)
        sc = _score_offset(cand)
        if sc > fine_score:
            fine_score = sc
            fine_best = cand
    return fine_best


def analyze_calibration_recording(
    wav_source: bytes | str | Path,
    expected_events: Sequence[Mapping[str, Any]],
    *,
    pattern_id: str | None = None,
    segments: Sequence[Mapping[str, Any]] | None = None,
    tolerance_ms: float = 45.0,
) -> dict[str, Any]:
    """Analyze a recorded in-game WAV against expected calibration events via onset detection."""
    if isinstance(wav_source, (str, Path)):
        p = Path(wav_source)
        if not p.is_file():
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"recording not found: {p.name}")
        raw_bytes = p.read_bytes()
    else:
        raw_bytes = bytes(wav_source)

    samples, sr = _decode_wav_mono(raw_bytes)
    detected_onsets, rms, _flux, noise_floor = _detect_onsets_from_envelope(samples, sr)
    clusters = _cluster_expected_onsets(expected_events)
    expected_times = [float(c["at_ms"]) for c in clusters]
    offset_ms = _estimate_global_offset_ms(
        expected_times, detected_onsets, tolerance_ms=tolerance_ms
    )

    # Closest-first bipartite assignment so skipped hits never steal an adjacent true onset
    candidate_pairs: list[tuple[float, int, int]] = []
    for cl_idx, cl in enumerate(clusters):
        target = cl["at_ms"] + offset_ms
        for d_idx, det_t in enumerate(detected_onsets):
            diff = abs(det_t - target)
            if diff <= tolerance_ms:
                candidate_pairs.append((diff, cl_idx, d_idx))
    candidate_pairs.sort(key=lambda item: (item[0], item[1], item[2]))

    matched_det_for_cluster: dict[int, int] = {}
    used_det: set[int] = set()
    for _diff, cl_idx, d_idx in candidate_pairs:
        if cl_idx in matched_det_for_cluster or d_idx in used_det:
            continue
        matched_det_for_cluster[cl_idx] = d_idx
        used_det.add(d_idx)

    cluster_matches: list[dict[str, Any]] = []
    errors_ms: list[float] = []
    for cl_idx, cl in enumerate(clusters):
        target = cl["at_ms"] + offset_ms
        best_idx = matched_det_for_cluster.get(cl_idx)
        matched = best_idx is not None
        det_ms = detected_onsets[best_idx] if best_idx is not None else None
        if best_idx is not None and det_ms is not None:
            errors_ms.append(round(det_ms - target, 2))
        cluster_matches.append({
            "expected_at_ms": cl["at_ms"],
            "chord_size": len(cl["events"]),
            "matched": matched,
            "detected_at_ms": round(det_ms, 2) if det_ms is not None else None,
            "timing_error_ms": round(det_ms - target, 2) if det_ms is not None else None,
        })

    segment_reports: list[dict[str, Any]] = []
    if segments:
        for seg in segments:
            s0 = int(seg["start_ms"])
            s1 = int(seg["end_ms"])
            in_seg = [m for m in cluster_matches if s0 <= m["expected_at_ms"] < s1]
            # Fallback inclusive boundary for single-event segments where start==end
            if not in_seg:
                in_seg = [m for m in cluster_matches if m["expected_at_ms"] == s0]
            hit = sum(1 for m in in_seg if m["matched"])
            tot = len(in_seg)
            segment_reports.append({
                **dict(seg),
                "matched_onsets": hit,
                "total_onsets": tot,
                "detection_rate": round(hit / tot, 4) if tot else 0.0,
            })

    matched_count = sum(1 for m in cluster_matches if m["matched"])
    total_clusters = len(cluster_matches)
    detection_rate = round(matched_count / total_clusters, 4) if total_clusters else 0.0

    # Infer empirical timing guidance where supported by pattern evidence
    suggested: dict[str, Any] = {"provisional": matched_count < 3}
    if pattern_id == "same_key_retrigger" and segment_reports:
        reliable = [
            int(s["interval_ms"])
            for s in segment_reports
            if s["detection_rate"] >= 0.75 and "interval_ms" in s
        ]
        if reliable:
            suggested["min_same_key_interval_ms"] = min(reliable)
    if pattern_id in {"distinct_key_rapid", "rapid_arpeggio"} and segment_reports:
        reliable = [
            int(s["interval_ms"])
            for s in segment_reports
            if s["detection_rate"] >= 0.75 and "interval_ms" in s
        ]
        if reliable:
            suggested["min_inter_key_interval_ms"] = min(reliable)
    if pattern_id == "hold_release_sweep" and segment_reports:
        reliable_pairs = [s for s in segment_reports if s["detection_rate"] >= 0.66]
        if reliable_pairs:
            suggested["min_key_hold_ms"] = min(int(s["hold_ms"]) for s in reliable_pairs)
            suggested["min_key_release_gap_ms"] = min(
                int(s["release_gap_ms"]) for s in reliable_pairs
            )
    if pattern_id == "instrument_sustain_trigger" and segment_reports and rms:
        short_decays: list[float] = []
        long_decays: list[float] = []
        hop_ms = 5.0
        for seg in segment_reports:
            if not seg["matched_onsets"]:
                continue
            start_frame = max(0, int(round((int(seg["start_ms"]) + offset_ms) / hop_ms)))
            end_frame = min(len(rms), start_frame + int(round(1200.0 / hop_ms)))
            window = rms[start_frame:end_frame]
            if not window:
                continue
            peak = max(window)
            decay_thresh = max(noise_floor * 2.5, peak * 0.25)
            last_above = 0
            for idx_f, val in enumerate(window):
                if val >= decay_thresh:
                    last_above = idx_f
            decay_ms = last_above * hop_ms
            if int(seg.get("hold_ms", 0)) <= 40:
                short_decays.append(decay_ms)
            else:
                long_decays.append(decay_ms)
        if short_decays and long_decays:
            mean_short = statistics.mean(short_decays)
            mean_long = statistics.mean(long_decays)
            suggested["short_hold_decay_ms"] = round(mean_short, 1)
            suggested["long_hold_decay_ms"] = round(mean_long, 1)
            suggested["trigger_mode"] = (
                "sustained" if mean_long > mean_short + 120.0 else "one_shot"
            )
            suggested["sustain_decay_ms"] = int(round(max(mean_short, mean_long)))

    return {
        "measurement_basis": "recorded_audio_onset_analysis",
        "pattern_id": pattern_id,
        "sample_rate": sr,
        "duration_ms": round(len(samples) / sr * 1000.0, 2),
        "estimated_offset_ms": round(offset_ms, 2),
        "expected_onset_clusters": total_clusters,
        "detected_onsets_total": len(detected_onsets),
        "matched_onsets": matched_count,
        "detection_rate": detection_rate,
        "mean_abs_error_ms": (
            round(statistics.mean(abs(x) for x in errors_ms), 2) if errors_ms else None
        ),
        "max_abs_error_ms": (
            round(max(abs(x) for x in errors_ms), 2) if errors_ms else None
        ),
        "segments": segment_reports,
        "suggested_timing": suggested,
        "clusters": cluster_matches[:200],
    }


__all__ = [
    "CALIBRATION_PATTERNS",
    "CalibrationPattern",
    "analyze_calibration_recording",
    "build_calibration_performance",
    "get_calibration_pattern",
    "list_calibration_patterns",
    "run_calibration_benchmark",
]
