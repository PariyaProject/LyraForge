"""Unit tests for isolated Windows playback abstractions (tested cross-platform)."""

from __future__ import annotations

import sys

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.playback import (
    DryRunDriver,
    NullFocusGuard,
    PlaybackMode,
    PlaybackState,
    Player,
    VirtualClock,
    create_playback_backend,
    is_windows_playback_available,
)
from lyraforge.playback.windows import (
    DEFAULT_ALLOWED_TITLES,
    ForegroundWindowGuard,
    KeyInputSpec,
    WindowsKeyboardDriver,
    build_key_input_spec,
)
from lyraforge.playback.windows.win32_types import KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE


def test_build_key_input_spec_for_all_windsong_lyre_keys() -> None:
    profile = load_builtin_profile()
    for key in profile.keys:
        down = build_key_input_spec(key.binding, key_up=False)
        up = build_key_input_spec(key.binding, key_up=True)
        assert down.binding == key.binding
        assert down.scan_code > 0
        assert down.flags == KEYEVENTF_SCANCODE
        assert not down.is_key_up
        assert up.scan_code == down.scan_code
        assert up.flags == (KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
        assert up.is_key_up

    with pytest.raises(LyraError) as exc:
        build_key_input_spec("F13", key_up=False)
    assert exc.value.code == ErrorCode.PROFILE_INVALID


def test_windows_keyboard_driver_mocked_and_release_all() -> None:
    profile = load_builtin_profile()
    sent: list[KeyInputSpec] = []
    driver = WindowsKeyboardDriver(profile, send_input_fn=sent.append)

    driver.key_down("low_1")
    driver.key_down("mid_1")
    # Re-pressing an already-held key emits key_up first
    driver.key_down("low_1")
    assert [s.binding for s in sent] == ["Z", "A", "Z", "Z"]
    assert [s.is_key_up for s in sent] == [False, False, True, False]
    assert driver.pressed == {"low_1", "mid_1"}

    released = driver.release_all()
    assert released == ["low_1", "mid_1"]
    assert driver.pressed == set()
    assert [s.is_key_up for s in sent[-2:]] == [True, True]

    with pytest.raises(LyraError) as exc:
        driver.key_down("nonexistent_key")
    assert exc.value.code == ErrorCode.PROFILE_INVALID


def test_windows_keyboard_driver_release_all_attempts_every_key_on_error() -> None:
    profile = load_builtin_profile()
    attempts: list[KeyInputSpec] = []

    def flaky_send(spec: KeyInputSpec) -> None:
        attempts.append(spec)
        if spec.is_key_up and spec.binding == "Z":
            raise OSError("simulated SendInput failure")

    driver = WindowsKeyboardDriver(profile, send_input_fn=flaky_send)
    driver.key_down("low_1")
    driver.key_down("mid_1")

    with pytest.raises(RuntimeError, match="failed releasing key"):
        driver.release_all()
    # Both Z and A key-ups were attempted despite Z failing
    assert [(s.binding, s.is_key_up) for s in attempts[-2:]] == [("Z", True), ("A", True)]
    assert driver.pressed == set()


def test_foreground_window_guard_allowlist_and_fail_closed() -> None:
    title = "Genshin Impact"
    guard = ForegroundWindowGuard(DEFAULT_ALLOWED_TITLES, get_title_fn=lambda: title)
    assert guard.is_target_focused()

    title = "原神"
    assert guard.is_target_focused()

    title = "Untitled - Notepad"
    assert not guard.is_target_focused()

    def broken_title() -> str:
        raise OSError("win32 failure")

    guard_broken = ForegroundWindowGuard(DEFAULT_ALLOWED_TITLES, get_title_fn=broken_title)
    assert not guard_broken.is_target_focused()

    with pytest.raises(LyraError) as exc:
        ForegroundWindowGuard(["", "  "], get_title_fn=lambda: "Genshin Impact")
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT


def test_player_with_mocked_windows_driver_focus_loss_releases_all() -> None:
    profile = load_builtin_profile()
    sent: list[KeyInputSpec] = []
    driver = WindowsKeyboardDriver(profile, send_input_fn=sent.append)
    calls = 0

    def title_sequence() -> str:
        nonlocal calls
        calls += 1
        return "Genshin Impact" if calls <= 2 else "Finder"

    guard = ForegroundWindowGuard(get_title_fn=title_sequence)
    clock = VirtualClock()
    player = Player(driver, clock, focus_guard=guard, poll_interval_us=10_000)
    res = player.play(
        [
            {"at_ms": 0, "key_id": "mid_1", "action": "tap", "hold_ms": 200},
            {"at_ms": 100, "key_id": "mid_3", "action": "tap", "hold_ms": 100},
        ]
    )
    assert res.state == PlaybackState.FOCUS_LOST
    assert res.released_keys == ["mid_1"]
    assert driver.pressed == set()
    assert [(s.binding, s.is_key_up) for s in sent] == [("A", False), ("A", True)]


def test_playback_factory_platform_behavior() -> None:
    profile = load_builtin_profile()
    clock = VirtualClock()
    driver, guard = create_playback_backend(PlaybackMode.DRY_RUN, profile=profile, clock=clock)
    assert isinstance(driver, DryRunDriver)
    assert isinstance(guard, NullFocusGuard)

    if sys.platform != "win32":
        assert not is_windows_playback_available()
        with pytest.raises(LyraError) as exc:
            create_playback_backend(PlaybackMode.WINDOWS, profile=profile, clock=clock)
        assert exc.value.code == ErrorCode.INVALID_ARGUMENT

        with pytest.raises(LyraError) as exc2:
            WindowsKeyboardDriver(profile)
        assert exc2.value.code == ErrorCode.INVALID_ARGUMENT

        with pytest.raises(LyraError) as exc3:
            ForegroundWindowGuard()
        assert exc3.value.code == ErrorCode.INVALID_ARGUMENT
