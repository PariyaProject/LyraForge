"""Unit tests for lyraforge.playback (Player, DryRunDriver, Clock, Guards)."""

from __future__ import annotations

import pytest

from lyraforge.playback import (
    DryRunDriver,
    MonotonicClock,
    PlaybackState,
    Player,
    StopToken,
    VirtualClock,
    expand_events,
)


def _ev(at_ms: int, key_id: str, hold_ms: int = 40) -> dict[str, object]:
    return {"at_ms": at_ms, "key_id": key_id, "action": "tap", "hold_ms": hold_ms}


def test_expand_events_up_before_down_at_equal_ms() -> None:
    actions = expand_events([_ev(0, "mid_1", 100), _ev(100, "mid_1", 100)])
    assert [(a.at_us, a.kind, a.key_id) for a in actions] == [
        (0, "down", "mid_1"),
        (100_000, "up", "mid_1"),
        (100_000, "down", "mid_1"),
        (200_000, "up", "mid_1"),
    ]


def test_virtual_clock_playback_exact_timestamps() -> None:
    clock = VirtualClock()
    driver = DryRunDriver(clock)
    player = Player(driver, clock)
    res = player.play([_ev(0, "mid_1", 40), _ev(100, "mid_2", 50)])
    assert res.state == PlaybackState.COMPLETED
    assert res.actions_sent == res.actions_total == 4
    assert res.max_lateness_us == 0
    assert driver.pressed == set()
    assert [(e.t_us, e.action, e.key_id) for e in driver.log] == [
        (0, "down", "mid_1"),
        (40_000, "up", "mid_1"),
        (100_000, "down", "mid_2"),
        (150_000, "up", "mid_2"),
    ]


def test_stop_token_mid_playback_releases_held_keys() -> None:
    clock = VirtualClock()
    driver = DryRunDriver(clock)
    stop = StopToken()

    class StoppingClock(VirtualClock):
        def sleep_us(self, us: int) -> None:
            super().sleep_us(us)
            if self.now_us() >= 50_000:
                stop.request_stop("user clicked stop")

    s_clock = StoppingClock()
    driver = DryRunDriver(s_clock)
    player = Player(driver, s_clock, stop_token=stop, poll_interval_us=10_000)
    res = player.play([_ev(0, "mid_1", 200), _ev(100, "mid_2", 100)])
    assert res.state == PlaybackState.STOPPED
    assert res.stop_reason == "user clicked stop"
    assert driver.pressed == set()
    assert res.released_keys == ["mid_1"]


def test_focus_lost_stops_and_releases_keys() -> None:
    clock = VirtualClock()
    driver = DryRunDriver(clock)

    class ToggleFocus:
        def __init__(self) -> None:
            self.calls = 0

        def is_target_focused(self) -> bool:
            self.calls += 1
            return self.calls <= 3

    player = Player(driver, clock, focus_guard=ToggleFocus(), poll_interval_us=10_000)
    res = player.play([_ev(0, "mid_1", 500), _ev(500, "mid_2", 500)])
    assert res.state == PlaybackState.FOCUS_LOST
    assert res.stop_reason == "target window lost focus"
    assert driver.pressed == set()
    assert "mid_1" in res.released_keys


def test_driver_exception_and_keyboard_interrupt_release_all() -> None:
    clock = VirtualClock()

    class FailingSecondDown(DryRunDriver):
        def key_down(self, key_id: str) -> None:
            if key_id == "mid_2":
                raise RuntimeError("boom")
            super().key_down(key_id)

    driver = FailingSecondDown(clock)
    player = Player(driver, clock)
    res = player.play([_ev(0, "mid_1", 500), _ev(20, "mid_2", 100)])
    assert res.state == PlaybackState.ERROR
    assert "RuntimeError: boom" in (res.error or "")
    assert driver.pressed == set()
    assert res.released_keys == ["mid_1"]

    class InterruptSecondDown(DryRunDriver):
        def key_down(self, key_id: str) -> None:
            if key_id == "mid_2":
                raise KeyboardInterrupt()
            super().key_down(key_id)

    driver2 = InterruptSecondDown(clock)
    player2 = Player(driver2, clock)
    with pytest.raises(KeyboardInterrupt):
        player2.play([_ev(0, "mid_1", 500), _ev(20, "mid_2", 100)])
    assert driver2.pressed == set()


def test_release_all_failure_falls_back_to_individual_key_ups() -> None:
    clock = VirtualClock()

    class FlakyReleaseDriver(DryRunDriver):
        def release_all(self) -> list[str]:
            raise OSError("release_all broke")

    driver = FlakyReleaseDriver(clock)
    stop = StopToken()
    driver_clock = VirtualClock()

    class StoppingClock(VirtualClock):
        def sleep_us(self, us: int) -> None:
            super().sleep_us(us)
            if self.now_us() >= 20_000:
                stop.request_stop("halt")

    c = StoppingClock()
    driver = FlakyReleaseDriver(c)
    player = Player(driver, c, stop_token=stop, poll_interval_us=10_000)
    res = player.play([_ev(0, "mid_1", 200)])
    assert res.state == PlaybackState.STOPPED
    assert "release_all broke" in (res.release_error or "")
    assert res.released_keys == ["mid_1"]
    assert driver.pressed == set()
    _ = driver_clock  # unused check avoided


@pytest.mark.realtime
def test_monotonic_clock_short_realtime_smoke() -> None:
    clock = MonotonicClock()
    driver = DryRunDriver(clock)
    player = Player(driver, clock, poll_interval_us=5_000)
    res = player.play([_ev(0, "mid_1", 20), _ev(40, "mid_2", 20)])
    assert res.state == PlaybackState.COMPLETED
    assert res.actions_sent == 4
    assert driver.pressed == set()
    assert res.ended_at_us - res.started_at_us >= 55_000
