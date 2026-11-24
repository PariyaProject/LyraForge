"""Repeatable playback timing precision & 3-tier benchmark verification script.

Usage:
  uv run python scripts/eval_playback.py
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from typing import Any

from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    ArrangeOptions,
    NormalizedScore,
    Note,
    TempoChange,
    TempoMap,
    TimeSignature,
    TimingMode,
    TrackInfo,
    arrange,
)
from lyraforge.music_core.arranger import Style
from lyraforge.playback import (
    DryRunDriver,
    LateEventPolicy,
    PlaybackOptions,
    Player,
    VirtualClock,
)
from lyraforge.playback.calibration import (
    analyze_calibration_recording,
    build_calibration_performance,
    run_calibration_benchmark,
)


def _score_from_notes(notes: list[Note], tracks: list[TrackInfo] | None = None) -> NormalizedScore:
    ordered = sorted(notes, key=lambda n: (n.start_us, n.pitch, n.track))
    if tracks is None:
        counts: dict[int, int] = {}
        for n in ordered:
            counts[n.track] = counts.get(n.track, 0) + 1
        tracks = [
            TrackInfo(index=t, name=f"Track {t}", note_count=c, channels=(0,))
            for t, c in sorted(counts.items())
        ]
    return NormalizedScore(
        source_sha256="eval-playback",
        midi_type=1 if len(tracks) > 1 else 0,
        ticks_per_beat=480,
        tempo_map=TempoMap(ticks_per_beat=480, changes=[TempoChange(0, 500_000)]),
        time_signatures=(TimeSignature(0, 0, 4, 4),),
        tracks=tuple(tracks),
        notes=tuple(ordered),
        duration_us=max((n.end_us for n in ordered), default=100_000),
        warnings=(),
    )


class _StallingClock(VirtualClock):
    def __init__(self, stall_us: int = 100_000) -> None:
        super().__init__()
        self._calls = 0
        self._stalled = False
        self._stall_us = stall_us

    def sleep_us(self, duration_us: int) -> None:
        super().sleep_us(duration_us)
        self._calls += 1
        if not self._stalled and self._calls >= 2:
            self._stalled = True
            self.advance(self._stall_us)


def _synth_wav(
    tones: list[tuple[float, float, float, float]],
    total_ms: int,
    sr: int = 22_050,
) -> bytes:
    n = int(round(total_ms * sr / 1000.0))
    buf = [0.0] * n
    for onset_ms, decay_ms, freq_hz, amp in tones:
        s0 = max(0, int(round(onset_ms * sr / 1000.0)))
        dur = max(1, int(round(decay_ms * 3.0 * sr / 1000.0)))
        for j in range(dur):
            idx = s0 + j
            if idx >= n:
                break
            t_s = j / sr
            env = math.exp(-t_s / max(0.01, decay_ms / 1000.0))
            buf[idx] += amp * env * math.sin(2 * math.pi * freq_hz * t_s)
    pcm = bytearray()
    for i, val in enumerate(buf):
        s = max(-0.98, min(0.98, val + 0.002 * math.sin(i * 0.71)))
        pcm.extend(struct.pack("<h", int(s * 32767)))
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(pcm))
    return out.getvalue()


def main() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    desc = [72, 71, 69, 67, 65, 64]

    arp_matrix: list[dict[str, Any]] = []
    for gap_ms in [5, 10, 15, 20, 30, 40, 50, 75, 100]:
        score = _score_from_notes([
            Note(p, 100, i * 10, i * 10 + 120, i * gap_ms * 1000, (i * gap_ms + 120) * 1000, 0, 0)
            for i, p in enumerate(desc)
        ])
        arr_bal = arrange(
            score,
            profile,
            ArrangeOptions(style=Style.BALANCED, transpose=0, arpeggiate_ms=12),
        )
        arr_mel = arrange(score, profile, ArrangeOptions(style=Style.MELODY, transpose=0))
        arr_2x = arrange(
            score,
            profile,
            ArrangeOptions(style=Style.BALANCED, transpose=0, arpeggiate_ms=12, speed=2.0),
        )
        bal_ok = [e.mapped_pitch for e in arr_bal.events] == desc and [
            e.at_ms for e in arr_bal.events
        ] == [i * gap_ms for i in range(6)]
        arp_matrix.append({
            "interval_ms": gap_ms,
            "balanced_1x_ok": bal_ok,
            "melody_1x_ok": [e.mapped_pitch for e in arr_mel.events] == desc,
            "balanced_2x_ok": (
                [e.mapped_pitch for e in arr_2x.events] == desc
                if gap_ms >= 10
                else "scaled_gap_2.5ms_enters_chord_window"
            ),
        })

    # Same-key legato repeats & cross-track collision
    rep_score = _score_from_notes([
        Note(60, 100, t, t + 200, t * 1000, (t + 200) * 1000, 0, 0)
        for t in [0, 50, 110, 190, 290, 410]
    ])
    rep_arr = arrange(
        rep_score,
        profile,
        ArrangeOptions(style=Style.MELODY, transpose=0, timing_mode=TimingMode.ADAPTED),
    )
    min_gap = min(
        rep_arr.events[i + 1].at_ms - (rep_arr.events[i].at_ms + rep_arr.events[i].hold_ms)
        for i in range(len(rep_arr.events) - 1)
    )

    cross_score = _score_from_notes(
        [
            Note(48, 85, 0, 100, 0, 100_000, 1, 1),
            Note(48, 110, 15, 120, 15_000, 120_000, 0, 0),
        ],
        tracks=[
            TrackInfo(0, "Vocal Lead", 1, (0,)),
            TrackInfo(1, "Piano Accomp", 1, (1,)),
        ],
    )
    cross_arr = arrange(
        cross_score,
        profile,
        ArrangeOptions(style=Style.BALANCED, transpose=0, melody_track=0),
    )

    # 100ms OS stall simulation across 3 policies
    stall_report: dict[str, Any] = {}
    stall_events = [{"at_ms": i * 30, "key_id": f"mid_{i + 1}", "hold_ms": 20} for i in range(5)]
    policies = (
        LateEventPolicy.SHIFT_CLOCK,
        LateEventPolicy.DROP_LATE,
        LateEventPolicy.CATCH_UP,
    )
    for policy in policies:
        clk = _StallingClock(100_000)
        drv = DryRunDriver(clk)
        res = Player(
            drv,
            clk,
            options=PlaybackOptions(late_event_policy=policy, late_threshold_ms=25),
        ).play(stall_events)
        downs = [e.t_us // 1000 for e in drv.log if e.action == "down"]
        stall_report[str(policy)] = {
            "down_times_ms": downs,
            "late_events_count": res.late_events_count,
            "late_events_dropped": res.late_events_dropped,
            "clock_shifts_count": res.clock_shifts_count,
        }

    # Tier 2 realtime MonotonicClock calibration benchmarks (shortened long_stability)
    rt_benchmarks = {}
    pat_ids = (
        "distinct_key_rapid",
        "same_key_retrigger",
        "chord_simultaneous",
        "rapid_arpeggio",
        "hold_release_sweep",
        "long_stability",
    )
    for pat_id in pat_ids:
        r = run_calibration_benchmark(
            pat_id,
            profile,
            realtime=True,
            duration_s=3.0 if pat_id == "long_stability" else None,
        )
        rt_benchmarks[pat_id] = {
            "expected_events": r["expected_events"],
            "drift_ms": r["drift_ms"],
            "cpu_pct": r["cpu_pct"],
            "p50_lateness_ms": r["result"]["p50_lateness_ms"],
            "p95_lateness_ms": r["result"]["p95_lateness_ms"],
            "p99_lateness_ms": r["result"]["p99_lateness_ms"],
            "max_lateness_ms": r["result"]["max_lateness_ms"],
            "overlapping_key_downs": r["log_verification"]["overlapping_key_downs"],
            "min_observed_release_gap_ms": r["log_verification"]["min_observed_release_gap_ms"],
        }

    # Synthetic WAV calibration roundtrip (B + G)
    built_b = build_calibration_performance("same_key_retrigger", profile)
    tones_b: list[tuple[float, float, float, float]] = []
    last_t = -1e9
    for ev in built_b["performance"]["events"]:
        at = float(ev["at_ms"])
        if at - last_t >= 60.0:
            tones_b.append((at + 60.0, 55.0, 523.25, 0.7))
            last_t = at
    ana_b = analyze_calibration_recording(
        _synth_wav(tones_b, built_b["performance"]["duration_ms"] + 400),
        built_b["performance"]["events"],
        pattern_id="same_key_retrigger",
        segments=built_b["segments"],
    )

    built_g = build_calibration_performance("instrument_sustain_trigger", profile)
    dur_g = built_g["performance"]["duration_ms"] + 1200
    tones_os = [
        (float(e["at_ms"]) + 10.0, 80.0, 392.0, 0.7) for e in built_g["performance"]["events"]
    ]
    ana_g_os = analyze_calibration_recording(
        _synth_wav(tones_os, dur_g),
        built_g["performance"]["events"],
        pattern_id="instrument_sustain_trigger",
        segments=built_g["segments"],
    )
    tones_sus = [
        (float(e["at_ms"]) + 10.0, 260.0 if int(e["hold_ms"]) >= 300 else 65.0, 392.0, 0.7)
        for e in built_g["performance"]["events"]
    ]
    ana_g_sus = analyze_calibration_recording(
        _synth_wav(tones_sus, dur_g),
        built_g["performance"]["events"],
        pattern_id="instrument_sustain_trigger",
        segments=built_g["segments"],
    )

    replacements = cross_arr.stats["timing_adjustments"]["melody_retrigger_replacements"]
    print(
        json.dumps(
            {
                "arpeggio_matrix": arp_matrix,
                "same_key_min_release_gap_ms": min_gap,
                "cross_track_winner_track": cross_arr.events[0].source_track,
                "cross_track_replacements": replacements,
                "stall_policies": stall_report,
                "realtime_benchmarks": rt_benchmarks,
                "wav_analysis_b": {
                    "offset_ms": ana_b["estimated_offset_ms"],
                    "detection_rate": ana_b["detection_rate"],
                    "suggested_timing": ana_b["suggested_timing"],
                },
                "wav_analysis_g_trigger": {
                    "one_shot": ana_g_os["suggested_timing"],
                    "sustained": ana_g_sus["suggested_timing"],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
