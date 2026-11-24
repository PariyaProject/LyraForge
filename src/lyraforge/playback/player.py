"""Scheduler / player: performance events -> timed driver calls.

Guarantees (tested in tests/unit/test_player.py & test_playback_precision.py):
* Overlapping or under-spaced same-key events are resolved deterministically
  before dispatch so an earlier NoteOff can never cut off a subsequent NoteOn,
  and same-key UP precedes DOWN cleanly (respecting ``min_key_release_gap_ms``).
* Simultaneous chord actions sharing ``(at_us, phase)`` are grouped and sent
  atomically via ``key_down_batch`` / ``key_up_batch`` when supported.
* Stop requests and focus loss are checked before every action and while
  waiting (every ``poll_interval_us``). Intermediate rests use coarse OS sleep
  (0% busy-wait), while only the final chunk uses sub-millisecond timing.
* ``release_all`` runs on *every* exit path (completion, stop, focus loss,
  driver exception, KeyboardInterrupt).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lyraforge.playback.clock import Clock
from lyraforge.playback.driver import PlaybackDriver
from lyraforge.playback.guards import FocusGuard, NullFocusGuard, PauseToken, StopToken

UP, DOWN = 0, 1


class LateEventPolicy(StrEnum):
    SHIFT_CLOCK = "shift_clock"
    DROP_LATE = "drop_late"
    CATCH_UP = "catch_up"


@dataclass(frozen=True, slots=True)
class PlaybackOptions:
    min_key_release_gap_ms: int = 0
    min_key_hold_ms: int = 1
    key_hold_ms_override: int | None = None
    speed: float = 1.0
    late_event_policy: LateEventPolicy = LateEventPolicy.SHIFT_CLOCK
    late_threshold_ms: int = 25
    late_warning_ms: int = 5
    record_trace: bool = False

    def __post_init__(self) -> None:
        if self.min_key_release_gap_ms < 0:
            raise ValueError("min_key_release_gap_ms must be >= 0")
        if self.min_key_hold_ms <= 0:
            raise ValueError("min_key_hold_ms must be > 0")
        if self.key_hold_ms_override is not None and self.key_hold_ms_override <= 0:
            raise ValueError("key_hold_ms_override must be > 0")
        if (
            not isinstance(self.speed, (int, float))
            or not math.isfinite(self.speed)
            or not (0.25 <= self.speed <= 4.0)
        ):
            raise ValueError("speed must be within [0.25, 4.0]")
        if self.late_threshold_ms <= 0:
            raise ValueError("late_threshold_ms must be > 0")
        if self.late_warning_ms < 0:
            raise ValueError("late_warning_ms must be >= 0")


@dataclass(frozen=True, order=True, slots=True)
class KeyAction:
    at_us: int
    phase: int  # UP (0) sorts before DOWN (1)
    seq: int
    key_id: str = field(compare=False)

    @property
    def kind(self) -> str:
        return "down" if self.phase == DOWN else "up"


def expand_events_with_stats(
    events: Iterable[Mapping[str, Any]],
    *,
    min_key_release_gap_ms: int = 0,
    min_key_hold_ms: int = 1,
    key_hold_ms_override: int | None = None,
    speed: float = 1.0,
) -> tuple[list[KeyAction], int]:
    """Expand performance events into sorted KeyActions, repairing same-key overlaps.

    Returns ``(actions, retrigger_conflicts_repaired)``.
    """
    if min_key_release_gap_ms < 0:
        raise ValueError("min_key_release_gap_ms must be >= 0")
    if min_key_hold_ms <= 0:
        raise ValueError("min_key_hold_ms must be > 0")
    if key_hold_ms_override is not None and key_hold_ms_override <= 0:
        raise ValueError("key_hold_ms_override must be > 0")
    if not (isinstance(speed, (int, float)) and math.isfinite(speed) and 0.25 <= speed <= 4.0):
        raise ValueError("speed must be within [0.25, 4.0]")

    parsed: list[tuple[int, int, int, str]] = []
    for seq, e in enumerate(events):
        if e.get("action", "tap") != "tap":
            raise ValueError(f"unsupported action {e.get('action')!r}")
        raw_at_ms = int(e["at_ms"])
        raw_hold_ms = (
            int(key_hold_ms_override) if key_hold_ms_override is not None else int(e["hold_ms"])
        )
        if raw_at_ms < 0 or raw_hold_ms <= 0:
            raise ValueError(f"invalid event timing at index {seq}")
        at_us = round(raw_at_ms * 1000 / speed)
        hold_us = max(int(min_key_hold_ms), raw_hold_ms) * 1000
        parsed.append((at_us, seq, hold_us, str(e["key_id"])))

    parsed.sort(key=lambda item: (item[0], item[1]))
    gap_us = int(min_key_release_gap_ms) * 1000
    min_hold_us = int(min_key_hold_ms) * 1000
    # key_id -> [[down_us, up_us, seq], ...]
    per_key: dict[str, list[list[int]]] = defaultdict(list)
    conflicts = 0

    for at_us, seq, hold_us, key_id in parsed:
        lane = per_key[key_id]
        if not lane:
            lane.append([at_us, at_us + hold_us, seq])
            continue
        prev = lane[-1]
        prev_down, prev_up, _ = prev
        if at_us == prev_down:
            conflicts += 1
            prev[1] = max(prev_up, at_us + hold_us)
            continue
        if prev_up > at_us - gap_us:
            conflicts += 1
            room = at_us - prev_down
            if room >= min_hold_us + gap_us:
                prev[1] = max(prev_down + min_hold_us, at_us - gap_us)
                cur_down = at_us
            else:
                shrunk_prev_up = max(prev_down + min_hold_us, at_us - gap_us)
                prev[1] = min(prev_up, shrunk_prev_up)
                cur_down = max(at_us, prev[1] + gap_us)
            cur_up = max(cur_down + min_hold_us, at_us + hold_us)
            lane.append([cur_down, cur_up, seq])
        else:
            lane.append([at_us, at_us + hold_us, seq])

    actions: list[KeyAction] = []
    for key_id, windows in per_key.items():
        for down_us, up_us, seq in windows:
            actions.append(KeyAction(down_us, DOWN, seq, key_id))
            actions.append(KeyAction(up_us, UP, seq, key_id))
    actions.sort()
    return actions, conflicts


def expand_events(
    events: Iterable[Mapping[str, Any]],
    *,
    min_key_release_gap_ms: int = 0,
    min_key_hold_ms: int = 1,
    key_hold_ms_override: int | None = None,
    speed: float = 1.0,
) -> list[KeyAction]:
    actions, _ = expand_events_with_stats(
        events,
        min_key_release_gap_ms=min_key_release_gap_ms,
        min_key_hold_ms=min_key_hold_ms,
        key_hold_ms_override=key_hold_ms_override,
        speed=speed,
    )
    return actions


class PlaybackState(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FOCUS_LOST = "focus_lost"
    ERROR = "error"
    INTERRUPTED = "interrupted"


def _percentile_us(samples: list[int], q: float) -> int:
    if not samples:
        return 0
    ordered = sorted(samples)
    idx = int(round((len(ordered) - 1) * q))
    return ordered[max(0, min(len(ordered) - 1, idx))]


@dataclass
class PlaybackResult:
    state: PlaybackState
    actions_total: int
    actions_sent: int = 0
    started_at_us: int = 0
    ended_at_us: int = 0
    max_lateness_us: int = 0
    total_lateness_us: int = 0
    lateness_samples_us: list[int] = field(default_factory=list)
    late_events_count: int = 0
    late_events_dropped: int = 0
    clock_shifts_count: int = 0
    total_clock_shift_us: int = 0
    retrigger_conflicts_count: int = 0
    late_event_policy: str = str(LateEventPolicy.SHIFT_CLOCK)
    min_key_release_gap_ms: int = 0
    trace: list[dict[str, Any]] | None = None
    stop_reason: str | None = None
    error: str | None = None
    released_keys: list[str] = field(default_factory=list)
    release_error: str | None = None

    @property
    def mean_lateness_us(self) -> float:
        return self.total_lateness_us / self.actions_sent if self.actions_sent else 0.0

    @property
    def p50_lateness_us(self) -> int:
        return _percentile_us(self.lateness_samples_us, 0.50)

    @property
    def p95_lateness_us(self) -> int:
        return _percentile_us(self.lateness_samples_us, 0.95)

    @property
    def p99_lateness_us(self) -> int:
        return _percentile_us(self.lateness_samples_us, 0.99)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": str(self.state),
            "actions_total": self.actions_total,
            "actions_sent": self.actions_sent,
            "elapsed_ms": round((self.ended_at_us - self.started_at_us) / 1000, 3),
            "max_lateness_ms": round(self.max_lateness_us / 1000, 3),
            "mean_lateness_ms": round(self.mean_lateness_us / 1000, 3),
            "p50_lateness_ms": round(self.p50_lateness_us / 1000, 3),
            "p95_lateness_ms": round(self.p95_lateness_us / 1000, 3),
            "p99_lateness_ms": round(self.p99_lateness_us / 1000, 3),
            "late_events_count": self.late_events_count,
            "late_events_dropped": self.late_events_dropped,
            "clock_shifts_count": self.clock_shifts_count,
            "total_clock_shift_ms": round(self.total_clock_shift_us / 1000, 3),
            "retrigger_conflicts_count": self.retrigger_conflicts_count,
            "late_event_policy": self.late_event_policy,
            "min_key_release_gap_ms": self.min_key_release_gap_ms,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "released_keys": self.released_keys,
            "release_error": self.release_error,
        }
        if self.trace is not None:
            payload["trace"] = self.trace
        return payload


class Player:
    def __init__(
        self,
        driver: PlaybackDriver,
        clock: Clock,
        focus_guard: FocusGuard | None = None,
        stop_token: StopToken | None = None,
        poll_interval_us: int = 10_000,
        pause_token: PauseToken | None = None,
        emergency_stop_fn: Callable[[], bool] | None = None,
        options: PlaybackOptions | None = None,
    ):
        if poll_interval_us <= 0:
            raise ValueError("poll_interval_us must be positive")
        self.driver = driver
        self.clock = clock
        self.focus_guard = focus_guard or NullFocusGuard()
        self.stop_token = stop_token or StopToken()
        self.poll_interval_us = poll_interval_us
        self.pause_token = pause_token
        self._emergency_stop_fn = emergency_stop_fn
        self.options = options or PlaybackOptions()

    def _interrupt_state(self) -> PlaybackState | None:
        if self.stop_token.stopped:
            return PlaybackState.STOPPED
        if self._emergency_stop_fn is not None:
            try:
                if self._emergency_stop_fn():
                    self.stop_token.request_stop("escape_key_pressed")
                    return PlaybackState.STOPPED
            except Exception:
                pass
        if not self.focus_guard.is_target_focused():
            return PlaybackState.FOCUS_LOST
        return None

    def _wait_if_paused(
        self,
        pressed: set[str],
        active_seq_by_key: dict[str, int],
        last_up_at: dict[str, int],
    ) -> tuple[int, PlaybackState | None]:
        if self.pause_token is None or not self.pause_token.paused:
            return 0, None
        paused_at = self.clock.now_us()
        if pressed:
            released_keys = list(pressed)
            self.driver.release_all()
            for k in released_keys:
                last_up_at[k] = paused_at
            pressed.clear()
            active_seq_by_key.clear()
        state = self._interrupt_state()
        coarse_sleep_fn = getattr(self.clock, "sleep_coarse_us", self.clock.sleep_us)
        while state is None and self.pause_token.paused:
            coarse_sleep_fn(self.poll_interval_us)
            state = self._interrupt_state()
        resumed_at = self.clock.now_us()
        return max(0, resumed_at - paused_at), state

    def _filter_group(
        self,
        phase: int,
        group: list[KeyAction],
        pressed: set[str],
        active_seq_by_key: dict[str, int],
        skipped_seqs: set[int],
    ) -> list[KeyAction]:
        if phase == DOWN:
            return [a for a in group if a.seq not in skipped_seqs]
        return [
            a
            for a in group
            if a.seq not in skipped_seqs
            and a.key_id in pressed
            and active_seq_by_key.get(a.key_id) == a.seq
        ]

    def _dispatch_group(
        self,
        phase: int,
        group: list[KeyAction],
        pressed: set[str],
        active_seq_by_key: dict[str, int],
        last_up_at: dict[str, int],
        now_us: int,
    ) -> None:
        key_ids = [a.key_id for a in group]
        if phase == DOWN:
            if len(group) > 1 and hasattr(self.driver, "key_down_batch"):
                try:
                    self.driver.key_down_batch(key_ids)
                except Exception:
                    pressed.update(key_ids)
                    raise
                for a in group:
                    pressed.add(a.key_id)
                    active_seq_by_key[a.key_id] = a.seq
            else:
                for a in group:
                    self.driver.key_down(a.key_id)
                    pressed.add(a.key_id)
                    active_seq_by_key[a.key_id] = a.seq
        else:
            if len(group) > 1 and hasattr(self.driver, "key_up_batch"):
                self.driver.key_up_batch(key_ids)
            else:
                for a in group:
                    self.driver.key_up(a.key_id)
            for a in group:
                pressed.discard(a.key_id)
                if active_seq_by_key.get(a.key_id) == a.seq:
                    del active_seq_by_key[a.key_id]
                last_up_at[a.key_id] = now_us

    def play(self, events: Iterable[Mapping[str, Any]]) -> PlaybackResult:
        opts = self.options
        actions, conflicts = expand_events_with_stats(
            events,
            min_key_release_gap_ms=opts.min_key_release_gap_ms,
            min_key_hold_ms=opts.min_key_hold_ms,
            key_hold_ms_override=opts.key_hold_ms_override,
            speed=opts.speed,
        )
        groups: list[tuple[int, int, list[KeyAction]]] = []
        for a in actions:
            if groups and groups[-1][0] == a.at_us and groups[-1][1] == a.phase:
                groups[-1][2].append(a)
            else:
                groups.append((a.at_us, a.phase, [a]))

        result = PlaybackResult(
            state=PlaybackState.COMPLETED,
            actions_total=len(actions),
            retrigger_conflicts_count=conflicts,
            late_event_policy=str(opts.late_event_policy),
            min_key_release_gap_ms=opts.min_key_release_gap_ms,
            trace=[] if opts.record_trace else None,
        )
        pressed: set[str] = set()
        active_seq_by_key: dict[str, int] = {}
        skipped_seqs: set[int] = set()
        last_up_at: dict[str, int] = {}
        gap_us = opts.min_key_release_gap_ms * 1000
        late_threshold_us = opts.late_threshold_ms * 1000
        late_warning_us = opts.late_warning_ms * 1000
        policy = LateEventPolicy(opts.late_event_policy)
        coarse_sleep_fn = getattr(self.clock, "sleep_coarse_us", self.clock.sleep_us)

        t0 = self.clock.now_us()
        pause_offset_us = 0
        clock_shift_us = 0
        result.started_at_us = t0
        try:
            for group_at_us, phase, group in groups:
                active = self._filter_group(phase, group, pressed, active_seq_by_key, skipped_seqs)
                if not active:
                    continue

                target = t0 + pause_offset_us + clock_shift_us + group_at_us
                state = self._interrupt_state()
                while state is None:
                    delta_pause, p_state = self._wait_if_paused(
                        pressed, active_seq_by_key, last_up_at
                    )
                    if delta_pause:
                        pause_offset_us += delta_pause
                        target = t0 + pause_offset_us + clock_shift_us + group_at_us
                        active = self._filter_group(
                            phase, group, pressed, active_seq_by_key, skipped_seqs
                        )
                        if not active:
                            break
                    if p_state is not None:
                        state = p_state
                        break
                    remaining = target - self.clock.now_us()
                    if remaining <= 0:
                        break
                    if remaining > self.poll_interval_us:
                        coarse_sleep_fn(self.poll_interval_us)
                    else:
                        self.clock.sleep_us(remaining)
                    state = self._interrupt_state()

                if state is not None:
                    result.state = state
                    result.stop_reason = (
                        self.stop_token.reason
                        if state == PlaybackState.STOPPED
                        else "target window lost focus"
                    )
                    break
                if not active:
                    continue

                # Wait any remaining real-time same-key release gap (e.g. after catch-up recovery)
                if phase == DOWN and gap_us > 0:
                    now_pre = self.clock.now_us()
                    need_wait = max(
                        (
                            gap_us - (now_pre - last_up_at[a.key_id])
                            for a in active
                            if a.key_id in last_up_at
                        ),
                        default=0,
                    )
                    while need_wait > 0:
                        self.clock.sleep_us(min(need_wait, self.poll_interval_us))
                        state = self._interrupt_state()
                        if state is not None:
                            break
                        now_pre = self.clock.now_us()
                        need_wait = max(
                            (
                                gap_us - (now_pre - last_up_at[a.key_id])
                                for a in active
                                if a.key_id in last_up_at
                            ),
                            default=0,
                        )
                    if state is not None:
                        result.state = state
                        result.stop_reason = (
                            self.stop_token.reason
                            if state == PlaybackState.STOPPED
                            else "target window lost focus"
                        )
                        break

                actual_now = self.clock.now_us()
                raw_lateness = max(0, actual_now - target)

                if phase == DOWN and raw_lateness > late_threshold_us:
                    if policy == LateEventPolicy.SHIFT_CLOCK:
                        clock_shift_us += raw_lateness
                        result.clock_shifts_count += 1
                        result.total_clock_shift_us += raw_lateness
                    elif policy == LateEventPolicy.DROP_LATE:
                        for a in active:
                            skipped_seqs.add(a.seq)
                            if result.trace is not None:
                                sched_rel = (target - t0 - pause_offset_us) / 1000
                                act_rel = (actual_now - t0 - pause_offset_us) / 1000
                                result.trace.append({
                                    "seq": a.seq,
                                    "key_id": a.key_id,
                                    "kind": "dropped_late",
                                    "scheduled_ms": round(sched_rel, 3),
                                    "actual_ms": round(act_rel, 3),
                                    "error_ms": round(raw_lateness / 1000, 3),
                                })
                        result.late_events_dropped += len(active)
                        continue

                self._dispatch_group(
                    phase, active, pressed, active_seq_by_key, last_up_at, actual_now
                )

                for a in active:
                    result.actions_sent += 1
                    result.total_lateness_us += raw_lateness
                    result.max_lateness_us = max(result.max_lateness_us, raw_lateness)
                    result.lateness_samples_us.append(raw_lateness)
                    if raw_lateness > late_warning_us:
                        result.late_events_count += 1
                    if result.trace is not None:
                        result.trace.append({
                            "seq": a.seq,
                            "key_id": a.key_id,
                            "kind": a.kind,
                            "scheduled_ms": round(group_at_us / 1000, 3),
                            "actual_ms": round((actual_now - t0 - pause_offset_us) / 1000, 3),
                            "error_ms": round(raw_lateness / 1000, 3),
                        })
        except Exception as exc:
            result.state = PlaybackState.ERROR
            result.error = f"{type(exc).__name__}: {exc}"
        except BaseException:
            result.state = PlaybackState.INTERRUPTED
            result.stop_reason = "interrupted"
            raise
        finally:
            self._release(pressed, result)
            result.ended_at_us = self.clock.now_us()
        return result

    def _release(self, pressed: set[str], result: PlaybackResult) -> None:
        try:
            result.released_keys = sorted(self.driver.release_all())
        except Exception as exc:  # fall back to individual key-ups
            result.release_error = f"{type(exc).__name__}: {exc}"
            for k in sorted(pressed):
                try:
                    self.driver.key_up(k)
                except Exception as exc2:  # keep trying the remaining keys
                    result.release_error += f"; key_up({k}) failed: {exc2}"
            result.released_keys = sorted(pressed)
