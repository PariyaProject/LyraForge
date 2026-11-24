"""Regression tests for full playback pipeline timing precision, arpeggio fidelity,
same-key retrigger protection, scheduler lateness policies, and Win32 driver hotpath.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

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
    with_timing_override,
)
from lyraforge.music_core.arranger import Style
from lyraforge.playback import (
    DryRunDriver,
    FocusGuard,
    LateEventPolicy,
    MonotonicClock,
    PauseToken,
    PlaybackOptions,
    PlaybackState,
    Player,
    StopToken,
    VirtualClock,
    expand_events_with_stats,
)
from lyraforge.playback.windows.driver import WindowsKeyboardDriver
from lyraforge.playback.windows.timer import high_resolution_timer
from lyraforge.playback.windows.win32_types import KeyInputSpec


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
    dur_us = max((n.end_us for n in ordered), default=100_000)
    return NormalizedScore(
        source_sha256="test-precision-sha",
        midi_type=1 if len(tracks) > 1 else 0,
        ticks_per_beat=480,
        tempo_map=TempoMap(ticks_per_beat=480, changes=[TempoChange(0, 500_000)]),
        time_signatures=(TimeSignature(0, 0, 4, 4),),
        tracks=tuple(tracks),
        notes=tuple(ordered),
        duration_us=dur_us,
        warnings=(),
    )


class _AlwaysFocused(FocusGuard):
    def is_target_focused(self) -> bool:
        return True


class _StallingClock(VirtualClock):
    """VirtualClock that injects a deterministic OS stall at a target timestamp."""

    def __init__(self, stall_after_calls: int = 2, stall_us: int = 100_000) -> None:
        super().__init__()
        self._sleep_calls = 0
        self._stall_after = stall_after_calls
        self._stall_us = stall_us
        self._stalled = False

    def sleep_us(self, duration_us: int) -> None:
        super().sleep_us(duration_us)
        self._sleep_calls += 1
        if not self._stalled and self._sleep_calls >= self._stall_after:
            self._stalled = True
            self.advance(self._stall_us)


# ---------------------------------------------------------------------------
# 1. Arpeggio vs Simultaneous Chord Discrimination (5..100 ms matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interval_ms", [5, 10, 15, 20, 30, 40, 50, 75, 100])
@pytest.mark.parametrize("direction", ["desc", "asc"])
def test_rapid_arpeggio_interval_matrix_preserves_order_and_all_notes(
    interval_ms: int, direction: str
) -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    pitches = [72, 71, 69, 67, 65, 64] if direction == "desc" else [60, 62, 64, 65, 67, 69]
    notes = [
        Note(
            pitch=p,
            velocity=100,
            start_tick=i * 10,
            end_tick=i * 10 + 120,
            start_us=i * interval_ms * 1000,
            end_us=(i * interval_ms + 120) * 1000,
            track=0,
            channel=0,
        )
        for i, p in enumerate(pitches)
    ]
    score = _score_from_notes(notes)

    configs = [
        (Style.BALANCED, 12, 1.0),
        (Style.MELODY, 0, 1.0),
    ]
    if interval_ms >= 10:
        # 5 ms @ 2.0x speed compresses inter-onset gap to 2.5 ms (< 4 ms chord window)
        configs.append((Style.BALANCED, 12, 2.0))

    for style, arp_ms, speed in configs:
        arr = arrange(
            score,
            profile,
            ArrangeOptions(
                style=style,
                transpose=0,
                arpeggiate_ms=arp_ms,
                speed=speed,
                timing_mode=TimingMode.ADAPTED,
            ),
        )
        assert len(arr.events) == 6, f"interval={interval_ms} style={style} speed={speed}"
        out_pitches = [e.mapped_pitch for e in arr.events]
        assert out_pitches == pitches
        expected_times = [int(round((i * interval_ms) / speed)) for i in range(6)]
        assert [e.at_ms for e in arr.events] == expected_times
        # Fast sequential arpeggio (>= 5 ms scaled) must not be treated as a simultaneous chord
        assert arr.stats["timing_adjustments"]["arpeggiated_events"] == 0


def _note(pitch: int, start_ms: int, dur_ms: int = 120, track: int = 0, vel: int = 100) -> Note:
    return Note(
        pitch=pitch,
        velocity=vel,
        start_tick=start_ms,
        end_tick=start_ms + dur_ms,
        start_us=start_ms * 1000,
        end_us=(start_ms + dur_ms) * 1000,
        track=track,
        channel=track,
    )


def test_true_simultaneous_chord_arpeggiates_while_5ms_arpeggio_stays_intact() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    chord_notes = [_note(60, 0, 200), _note(64, 2, 200), _note(67, 4, 200)]
    chord_arr = arrange(
        _score_from_notes(chord_notes),
        profile,
        ArrangeOptions(style=Style.BALANCED, transpose=0, arpeggiate_ms=12),
    )
    assert [e.mapped_pitch for e in chord_arr.events] == [60, 64, 67]
    assert [e.at_ms for e in chord_arr.events] == [0, 12, 24]
    # Anchor note stays at 0 ms; the remaining 2 chord voices are staggered by arpeggiate_ms
    assert chord_arr.stats["timing_adjustments"]["arpeggiated_events"] == 2


# ---------------------------------------------------------------------------
# 2. Same-Key Retrigger, Cross-Track Priority, Folding & Speed Scaling
# ---------------------------------------------------------------------------


def test_legato_same_key_repeats_enforce_release_gap_in_adapted_vs_strict_mode() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    onsets_ms = [0, 50, 110, 190, 290, 410]
    notes = [
        Note(
            pitch=60,
            velocity=100,
            start_tick=t,
            end_tick=t + 200,
            start_us=t * 1000,
            end_us=(t + 200) * 1000,
            track=0,
            channel=0,
        )
        for t in onsets_ms
    ]
    score = _score_from_notes(notes)

    adapted = arrange(
        score,
        profile,
        ArrangeOptions(style=Style.MELODY, transpose=0, timing_mode=TimingMode.ADAPTED),
    )
    assert [e.at_ms for e in adapted.events] == onsets_ms
    gaps = [
        adapted.events[i + 1].at_ms - (adapted.events[i].at_ms + adapted.events[i].hold_ms)
        for i in range(len(adapted.events) - 1)
    ]
    assert all(g >= profile.timing.min_key_release_gap_ms for g in gaps)
    assert adapted.stats["timing_adjustments"]["hold_shortened_for_retrigger"] > 0

    strict = arrange(
        score,
        profile,
        ArrangeOptions(
            style=Style.MELODY,
            transpose=0,
            arpeggiate_ms=12,
            timing_mode=TimingMode.STRICT_FIDELITY,
        ),
    )
    assert strict.stats["timing_mode"] == "strict_fidelity"
    assert [e.at_ms for e in strict.events] == onsets_ms
    # Even strict_fidelity preserves physical non-overlap on same-key repeats
    strict_gaps = [
        strict.events[i + 1].at_ms - (strict.events[i].at_ms + strict.events[i].hold_ms)
        for i in range(len(strict.events) - 1)
    ]
    assert all(g >= profile.timing.min_key_release_gap_ms for g in strict_gaps)


def test_cross_track_same_key_collision_keeps_melody_track_over_accompaniment() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    # Track 1 (accomp) plays C3 (low_1) at 0 ms; Track 0 (melody) needs low_1 at 15 ms
    tracks = [
        TrackInfo(index=0, name="Vocal Lead", note_count=1, channels=(0,)),
        TrackInfo(index=1, name="Piano Accomp", note_count=1, channels=(1,)),
    ]
    notes = [
        _note(48, 0, 100, track=1, vel=85),
        _note(48, 15, 105, track=0, vel=110),
    ]
    score = _score_from_notes(notes, tracks=tracks)

    arr_classic = arrange(
        score,
        profile,
        ArrangeOptions(
            style=Style.BALANCED,
            transpose=0,
            arranger_strategy="classic",
            melody_track=0,
        ),
    )
    assert len(arr_classic.events) == 1
    assert arr_classic.events[0].source_track == 0
    assert arr_classic.events[0].at_ms == 15
    assert arr_classic.stats["timing_adjustments"]["melody_retrigger_replacements"] >= 1

    arr_vocal = arrange(
        score,
        profile,
        ArrangeOptions(
            style=Style.BALANCED,
            transpose=0,
            arranger_strategy="vocal_lead",
            melody_track=0,
        ),
    )
    assert len(arr_vocal.events) == 1
    assert arr_vocal.events[0].source_track == 0
    assert arr_vocal.events[0].at_ms == 15


def test_octave_folded_different_midi_pitches_same_key_do_not_overlap() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    # C4 (60) maps to mid_1 directly; C7 (96) folds down to high_1 (84) vs C2 (36) -> low_1 (48)
    # Test C3 (48 -> low_1) and C2 (36 -> folds up to low_1) within 60 ms
    notes = [_note(48, 0, 100), _note(36, 60, 100)]
    arr = arrange(
        _score_from_notes(notes),
        profile,
        ArrangeOptions(style=Style.BALANCED, transpose=0, timing_mode=TimingMode.ADAPTED),
    )
    assert len(arr.events) == 2
    assert arr.events[0].key_id == arr.events[1].key_id == "low_1"
    e0, e1 = arr.events
    assert e0.at_ms + e0.hold_ms + profile.timing.min_key_release_gap_ms <= e1.at_ms


def test_player_repairs_overlapping_same_key_events_with_deterministic_release_gap() -> None:
    events = [
        {"at_ms": 0, "key_id": "mid_1", "hold_ms": 60},
        {"at_ms": 30, "key_id": "mid_1", "hold_ms": 60},
    ]
    actions, conflicts = expand_events_with_stats(
        events, min_key_release_gap_ms=20, min_key_hold_ms=5
    )
    assert conflicts == 1
    assert [(a.at_us // 1000, a.kind, a.seq) for a in actions] == [
        (0, "down", 0),
        (10, "up", 0),
        (30, "down", 1),
        (90, "up", 1),
    ]

    clock = VirtualClock()
    driver = DryRunDriver(clock)
    player = Player(
        driver,
        clock,
        options=PlaybackOptions(min_key_release_gap_ms=20, min_key_hold_ms=5),
    )
    result = player.play(events)
    assert result.state == PlaybackState.COMPLETED
    assert result.retrigger_conflicts_count == 1
    assert [(e.t_us // 1000, e.action, e.key_id) for e in driver.log] == [
        (0, "down", "mid_1"),
        (10, "up", "mid_1"),
        (30, "down", "mid_1"),
        (90, "up", "mid_1"),
    ]


def test_speed_scaled_tight_repeat_and_pause_resume_keep_clean_release_state() -> None:
    # 2x speed compresses at_ms=50, hold_ms=40 -> 25ms, hold=20 -> overlaps with release_gap=15
    actions, conflicts = expand_events_with_stats(
        [
            {"at_ms": 0, "key_id": "mid_1", "hold_ms": 40},
            {"at_ms": 50, "key_id": "mid_1", "hold_ms": 40},
        ],
        min_key_release_gap_ms=15,
        min_key_hold_ms=5,
        speed=2.0,
    )
    assert conflicts == 1
    assert [(a.at_us // 1000, a.kind) for a in actions] == [
        (0, "down"),
        (10, "up"),
        (25, "down"),
        (65, "up"),
    ]

    # Pause mid-hold releases active key cleanly and ignores stale pre-pause UP after resume
    pause_token = PauseToken()
    stop_token = StopToken()

    class _PauseAndStopClock(VirtualClock):
        def __init__(self) -> None:
            super().__init__()
            self._paused_once = False
            self._resumed = False

        def sleep_us(self, duration_us: int) -> None:
            super().sleep_us(duration_us)
            if not self._paused_once and self.now_us() >= 20_000:
                self._paused_once = True
                pause_token.pause()
            elif (
                self._paused_once
                and not self._resumed
                and pause_token.paused
                and self.now_us() >= 50_000
            ):
                self._resumed = True
                pause_token.resume()

    p_clock = _PauseAndStopClock()
    driver = DryRunDriver(p_clock)
    player = Player(
        driver,
        p_clock,
        pause_token=pause_token,
        stop_token=stop_token,
        poll_interval_us=5_000,
        options=PlaybackOptions(min_key_release_gap_ms=20),
    )
    res = player.play([
        {"at_ms": 0, "key_id": "mid_1", "hold_ms": 80},
        {"at_ms": 90, "key_id": "mid_1", "hold_ms": 40},
    ])
    assert res.state == PlaybackState.COMPLETED
    # Never emits two consecutive downs without UP/release in between
    pressed_now: set[str] = set()
    for entry in driver.log:
        if entry.action == "down":
            assert entry.key_id not in pressed_now
            pressed_now.add(entry.key_id)
        else:
            pressed_now.discard(entry.key_id)
    assert not driver.pressed


# ---------------------------------------------------------------------------
# 3. Built-in Profile Hashes & One-Shot vs Sustained Trigger Mode
# ---------------------------------------------------------------------------


def test_builtin_profile_hashes_preserved_and_trigger_mode_differentiates_holds() -> None:
    expected_hashes = {
        "genshin.windsong_lyre.v1": (
            "sha256:ed5b2c1d1cf6bdad9a036696c1eb430275510479129912909f752e1c7be18b86"
        ),
        "genshin.floral_zither.v1": (
            "sha256:6b59adf9ffe985106c0184b3c7074cfaef1bf12eabf1c479480fc1a82e8c9e0f"
        ),
        "genshin.vintage_lyre.v1": (
            "sha256:82da2263327eac963a35f58661c68eb0e9e5fc02169667bbb0a69da57bc5b2f1"
        ),
    }
    for pid, expected_hash in expected_hashes.items():
        prof = load_builtin_profile(pid)
        assert prof.hash == expected_hash
        assert prof.timing.min_key_release_gap_ms == 20
        assert prof.timing.trigger_mode == "one_shot"
        assert prof.timing.provisional is True

    # Sustained instrument keeps long hold closer to MIDI note duration, unlike one-shot
    windsong = load_builtin_profile("genshin.windsong_lyre.v1")
    sustained = with_timing_override(windsong, trigger_mode="sustained", max_key_hold_ms=600)
    score = _score_from_notes([_note(60, 0, 500)])
    one_shot_arr = arrange(score, windsong, ArrangeOptions(transpose=0))
    sustained_arr = arrange(score, sustained, ArrangeOptions(transpose=0))
    assert one_shot_arr.events[0].hold_ms <= 120
    assert sustained_arr.events[0].hold_ms == 500


# ---------------------------------------------------------------------------
# 4. Late-Event Policies, Trace Diagnostics & Win32 Batch/Timer Hardening
# ---------------------------------------------------------------------------


def test_scheduler_lateness_policies_shift_drop_and_catchup_plus_diagnostics() -> None:
    arpeggio_events = [
        {"at_ms": i * 30, "key_id": f"mid_{i + 1}", "hold_ms": 20} for i in range(5)
    ]

    # SHIFT_CLOCK shifts remaining arpeggio cleanly after 100ms stall without clumping chords
    shift_clock = _StallingClock(stall_after_calls=2, stall_us=100_000)
    shift_driver = DryRunDriver(shift_clock)
    shift_res = Player(
        shift_driver,
        shift_clock,
        focus_guard=_AlwaysFocused(),
        options=PlaybackOptions(
            late_event_policy=LateEventPolicy.SHIFT_CLOCK,
            late_threshold_ms=25,
            record_trace=True,
        ),
    ).play(arpeggio_events)
    down_times = [e.t_us // 1000 for e in shift_driver.log if e.action == "down"]
    assert shift_res.clock_shifts_count >= 1
    assert shift_res.total_clock_shift_us >= 80_000
    assert len(down_times) == 5
    # Notes 2..5 keep >= 30ms spacing instead of collapsing simultaneously
    for a, b in zip(down_times[1:-1], down_times[2:], strict=True):
        assert b - a >= 25
    assert shift_res.trace is not None and len(shift_res.trace) == 10
    j = shift_res.to_json()
    for key in (
        "p50_lateness_ms",
        "p95_lateness_ms",
        "p99_lateness_ms",
        "max_lateness_ms",
        "late_events_count",
    ):
        assert key in j

    # DROP_LATE drops stale delayed note rather than firing an out-of-time burst
    drop_clock = _StallingClock(stall_after_calls=2, stall_us=100_000)
    drop_driver = DryRunDriver(drop_clock)
    drop_res = Player(
        drop_driver,
        drop_clock,
        options=PlaybackOptions(
            late_event_policy=LateEventPolicy.DROP_LATE,
            late_threshold_ms=25,
            record_trace=True,
        ),
    ).play(arpeggio_events)
    assert drop_res.late_events_dropped >= 1
    assert drop_res.trace is not None and any(t["kind"] == "dropped_late" for t in drop_res.trace)

    # CATCH_UP records late_events_count against fixed timeline
    cu_clock = _StallingClock(stall_after_calls=2, stall_us=100_000)
    cu_driver = DryRunDriver(cu_clock)
    cu_res = Player(
        cu_driver,
        cu_clock,
        options=PlaybackOptions(late_event_policy=LateEventPolicy.CATCH_UP, late_threshold_ms=25),
    ).play(arpeggio_events)
    assert cu_res.late_events_count >= 1


def test_windows_keyboard_driver_batch_send_and_failure_recovery() -> None:
    profile = load_builtin_profile("genshin.windsong_lyre.v1")
    sent_singles: list[tuple[int, int]] = []
    sent_batches: list[list[tuple[int, int]]] = []

    drv = WindowsKeyboardDriver(
        profile,
        send_input_fn=lambda spec: sent_singles.append((spec.scan_code, spec.flags)),
        send_batch_fn=lambda specs: sent_batches.append([(s.scan_code, s.flags) for s in specs]),
    )
    drv.key_down_batch(["mid_1", "mid_3", "mid_5"])
    assert len(sent_batches) == 1 and len(sent_batches[0]) == 3
    assert drv.pressed == {"mid_1", "mid_3", "mid_5"}

    # Failed key_up_batch falls back cleanly to retried per-key key_up
    drv_fallback = WindowsKeyboardDriver(
        profile,
        send_input_fn=lambda spec: sent_singles.append((spec.scan_code, spec.flags)),
        send_batch_fn=lambda specs: (_ for _ in ()).throw(OSError("batch fail"))
        if any(s.flags & 2 for s in specs)
        else sent_batches.append([(s.scan_code, s.flags) for s in specs]),
    )
    drv_fallback.key_down_batch(["mid_1", "mid_3"])
    drv_fallback.key_up_batch(["mid_1", "mid_3"])
    assert drv_fallback.pressed == set()
    assert len(sent_singles) >= 2

    # Partial key_down_batch failure conservatively marks keys so release_all() releases them
    class _FailDownBatch:
        def __call__(self, specs: list[KeyInputSpec]) -> None:
            raise OSError("partial batch failure")

    drv_partial = WindowsKeyboardDriver(
        profile,
        send_input_fn=lambda spec: sent_singles.append((spec.scan_code, spec.flags)),
        send_batch_fn=_FailDownBatch(),
    )
    with pytest.raises(OSError, match="partial batch failure"):
        drv_partial.key_down_batch(["mid_1", "mid_3"])
    assert drv_partial.pressed == {"mid_1", "mid_3"}
    released = drv_partial.release_all()
    assert sorted(released) == ["mid_1", "mid_3"]
    assert drv_partial.pressed == set()


def test_high_resolution_timer_mocked_win32_pairs_begin_and_end_period(monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []

    class _FakeWinmm:
        def timeBeginPeriod(self, p: int) -> int:
            calls.append(("begin", p))
            return 0

        def timeEndPeriod(self, p: int) -> int:
            calls.append(("end", p))
            return 0

    fake_ctypes = types.SimpleNamespace(WinDLL=lambda name, use_last_error=False: _FakeWinmm())
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    with pytest.raises(RuntimeError), high_resolution_timer(1):
        raise RuntimeError("boom")
    assert calls == [("begin", 1), ("end", 1)]


def test_monotonic_clock_realtime_arpeggio_zero_overlaps() -> None:
    clock = MonotonicClock()
    driver = DryRunDriver(clock)
    player = Player(
        driver,
        clock,
        poll_interval_us=10_000,
        options=PlaybackOptions(min_key_release_gap_ms=20, record_trace=True),
    )
    events = [
        {"at_ms": 0, "key_id": "mid_1", "hold_ms": 30},
        {"at_ms": 20, "key_id": "mid_2", "hold_ms": 20},
        {"at_ms": 40, "key_id": "mid_1", "hold_ms": 20},
        {"at_ms": 70, "key_id": "mid_3", "hold_ms": 20},
    ]
    res = player.play(events)
    assert res.state == PlaybackState.COMPLETED
    assert res.actions_sent == 8
    assert res.p95_lateness_us < 25_000
    # Verify non-overlapping same-key UP/DOWN in recorded log
    last_up: dict[str, int] = {}
    for entry in driver.log:
        if entry.action == "down" and entry.key_id in last_up:
            assert entry.t_us - last_up[entry.key_id] >= 18_000
        elif entry.action in {"up", "release"}:
            last_up[entry.key_id] = entry.t_us
