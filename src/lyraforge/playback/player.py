"""Scheduler / player: performance events -> timed driver calls.

Guarantees (tested in tests/unit/test_player.py):
* Actions are ordered by time; at equal times key-ups precede key-downs so a
  key can be re-pressed on the same millisecond it is released.
* Stop requests and focus loss are checked before every action and while
  waiting (every ``poll_interval_us``).
* ``release_all`` runs on *every* exit path (completion, stop, focus loss,
  driver exception, KeyboardInterrupt). If the driver's own release fails, the
  player falls back to individual key-ups for every key it pressed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lyraforge.playback.clock import Clock
from lyraforge.playback.driver import PlaybackDriver
from lyraforge.playback.guards import FocusGuard, NullFocusGuard, StopToken

UP, DOWN = 0, 1


@dataclass(frozen=True, order=True, slots=True)
class KeyAction:
    at_us: int
    phase: int  # UP (0) sorts before DOWN (1)
    seq: int
    key_id: str = field(compare=False)

    @property
    def kind(self) -> str:
        return "down" if self.phase == DOWN else "up"


def expand_events(events: Iterable[Mapping[str, Any]]) -> list[KeyAction]:
    actions: list[KeyAction] = []
    for seq, e in enumerate(events):
        if e.get("action", "tap") != "tap":
            raise ValueError(f"unsupported action {e.get('action')!r}")
        at_us = int(e["at_ms"]) * 1000
        hold_us = int(e["hold_ms"]) * 1000
        if at_us < 0 or hold_us <= 0:
            raise ValueError(f"invalid event timing at index {seq}")
        actions.append(KeyAction(at_us, DOWN, seq, e["key_id"]))
        actions.append(KeyAction(at_us + hold_us, UP, seq, e["key_id"]))
    actions.sort()
    return actions


class PlaybackState(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FOCUS_LOST = "focus_lost"
    ERROR = "error"
    INTERRUPTED = "interrupted"


@dataclass
class PlaybackResult:
    state: PlaybackState
    actions_total: int
    actions_sent: int = 0
    started_at_us: int = 0
    ended_at_us: int = 0
    max_lateness_us: int = 0
    total_lateness_us: int = 0
    stop_reason: str | None = None
    error: str | None = None
    released_keys: list[str] = field(default_factory=list)
    release_error: str | None = None

    @property
    def mean_lateness_us(self) -> float:
        return self.total_lateness_us / self.actions_sent if self.actions_sent else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "actions_total": self.actions_total,
            "actions_sent": self.actions_sent,
            "elapsed_ms": round((self.ended_at_us - self.started_at_us) / 1000, 3),
            "max_lateness_ms": round(self.max_lateness_us / 1000, 3),
            "mean_lateness_ms": round(self.mean_lateness_us / 1000, 3),
            "stop_reason": self.stop_reason,
            "error": self.error,
            "released_keys": self.released_keys,
            "release_error": self.release_error,
        }


class Player:
    def __init__(self, driver: PlaybackDriver, clock: Clock,
                 focus_guard: FocusGuard | None = None, stop_token: StopToken | None = None,
                 poll_interval_us: int = 10_000):
        if poll_interval_us <= 0:
            raise ValueError("poll_interval_us must be positive")
        self.driver = driver
        self.clock = clock
        self.focus_guard = focus_guard or NullFocusGuard()
        self.stop_token = stop_token or StopToken()
        self.poll_interval_us = poll_interval_us

    def _interrupt_state(self) -> PlaybackState | None:
        if self.stop_token.stopped:
            return PlaybackState.STOPPED
        if not self.focus_guard.is_target_focused():
            return PlaybackState.FOCUS_LOST
        return None

    def play(self, events: Iterable[Mapping[str, Any]]) -> PlaybackResult:
        actions = expand_events(events)
        result = PlaybackResult(state=PlaybackState.COMPLETED, actions_total=len(actions))
        pressed: set[str] = set()
        t0 = self.clock.now_us()
        result.started_at_us = t0
        try:
            for a in actions:
                target = t0 + a.at_us
                state = self._interrupt_state()
                while state is None and (remaining := target - self.clock.now_us()) > 0:
                    self.clock.sleep_us(min(remaining, self.poll_interval_us))
                    state = self._interrupt_state()
                if state is not None:
                    result.state = state
                    result.stop_reason = (self.stop_token.reason if state == PlaybackState.STOPPED
                                          else "target window lost focus")
                    break
                lateness = max(0, self.clock.now_us() - target)
                if a.phase == DOWN:
                    self.driver.key_down(a.key_id)
                    pressed.add(a.key_id)
                else:
                    self.driver.key_up(a.key_id)
                    pressed.discard(a.key_id)
                result.actions_sent += 1
                result.total_lateness_us += lateness
                result.max_lateness_us = max(result.max_lateness_us, lateness)
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
