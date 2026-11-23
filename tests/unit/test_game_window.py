"""Tests for process-based game detection, UIPI elevation guidance and focus waiting."""

from __future__ import annotations

import pytest

from lyraforge.api.playback_service import PlaybackManager
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.playback.guards import StopToken
from lyraforge.playback.windows.game_window import (
    ForegroundWindowInfo,
    elevation_blocker,
)
from lyraforge.playback.windows.window_guard import ForegroundWindowGuard


def _info(process_name: str, title: str, elevated: bool | None = False) -> ForegroundWindowInfo:
    return ForegroundWindowInfo(1, 42, process_name, title, elevated)


def test_guard_matches_game_process_regardless_of_title() -> None:
    guard = ForegroundWindowGuard(
        ("Genshin Impact", "原神"),
        allowed_processes=("GenshinImpact.exe", "YuanShen.exe"),
        get_info_fn=lambda: _info("YuanShen.exe", "原神"),
    )
    assert guard.is_target_focused()

    titled = ForegroundWindowGuard(
        ("Genshin Impact", "原神"),
        allowed_processes=("YuanShen.exe",),
        get_info_fn=lambda: _info("GenshinImpact.exe", "Genshin Impact"),
    )
    assert titled.is_target_focused()  # title fallback still works


def test_guard_rejects_other_process_and_title() -> None:
    guard = ForegroundWindowGuard(
        ("Genshin Impact", "原神"),
        allowed_processes=("YuanShen.exe",),
        get_info_fn=lambda: _info("chrome.exe", "Notepad - 无标题"),
    )
    assert not guard.is_target_focused()


def test_guard_requires_a_non_empty_allowlist() -> None:
    with pytest.raises(LyraError) as exc:
        ForegroundWindowGuard((), get_info_fn=lambda: _info("YuanShen.exe", "原神"))
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT


def test_elevation_blocker_is_actionable_only_when_uipi_would_drop_input() -> None:
    assert elevation_blocker(True, False) is not None
    assert "管理员" in (elevation_blocker(True, False) or "")
    assert elevation_blocker(None, False) is not None
    assert elevation_blocker(True, True) is None
    assert elevation_blocker(False, False) is None
    assert elevation_blocker(None, True) is None


def test_guard_permission_problem_uses_target_and_own_elevation(monkeypatch) -> None:
    monkeypatch.setattr(
        "lyraforge.playback.windows.window_guard.current_process_elevated", lambda: False
    )
    admin_game = ForegroundWindowGuard(
        (),
        allowed_processes=("YuanShen.exe",),
        get_info_fn=lambda: _info("YuanShen.exe", "原神", True),
    )
    assert admin_game.permission_problem() is not None

    normal_game = ForegroundWindowGuard(
        (),
        allowed_processes=("YuanShen.exe",),
        get_info_fn=lambda: _info("YuanShen.exe", "原神", False),
    )
    assert normal_game.permission_problem() is None


class _FakeGuard:
    def __init__(self, focused: bool) -> None:
        self._focused = focused

    def is_target_focused(self) -> bool:
        return self._focused


def test_wait_for_focus_succeeds_or_times_out_without_sending_keys() -> None:
    assert PlaybackManager._wait_for_focus(_FakeGuard(True), StopToken(), 0.2) is True
    assert PlaybackManager._wait_for_focus(_FakeGuard(False), StopToken(), 0.05) is False

    stopped = StopToken()
    stopped.request_stop("user")
    assert PlaybackManager._wait_for_focus(_FakeGuard(False), stopped, 1.0) is False
