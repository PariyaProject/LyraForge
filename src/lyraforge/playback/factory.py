"""Cross-platform playback backend factory.

Defaults to ``DryRunDriver`` on macOS / non-Windows platforms and lazy-loads
``lyraforge.playback.windows`` ONLY when running on ``win32``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from enum import StrEnum

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.playback.clock import Clock
from lyraforge.playback.driver import DryRunDriver, PlaybackDriver
from lyraforge.playback.guards import FocusGuard, NullFocusGuard


class PlaybackMode(StrEnum):
    DRY_RUN = "dry-run"
    WINDOWS = "windows"


def is_windows_playback_available() -> bool:
    return sys.platform == "win32"


def create_playback_backend(
    mode: PlaybackMode,
    *,
    profile: InstrumentProfile,
    clock: Clock,
    allowed_window_titles: Sequence[str] | None = None,
    allowed_processes: Sequence[str] | None = None,
) -> tuple[PlaybackDriver, FocusGuard]:
    """Build ``(driver, focus_guard)`` for the requested playback mode."""
    mode = PlaybackMode(mode)
    if mode == PlaybackMode.DRY_RUN:
        return DryRunDriver(clock), NullFocusGuard()

    if not is_windows_playback_available():
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"windows playback mode is not supported on platform {sys.platform!r}; use dry-run",
            {"platform": sys.platform},
        )

    from lyraforge.playback.windows import (
        DEFAULT_ALLOWED_PROCESSES,
        DEFAULT_ALLOWED_TITLES,
        ForegroundWindowGuard,
        WindowsKeyboardDriver,
    )

    titles = tuple(allowed_window_titles) if allowed_window_titles else DEFAULT_ALLOWED_TITLES
    processes = (
        tuple(allowed_processes) if allowed_processes else DEFAULT_ALLOWED_PROCESSES
    )
    return WindowsKeyboardDriver(profile), ForegroundWindowGuard(
        titles, allowed_processes=processes
    )


def create_emergency_stop_checker(mode: PlaybackMode) -> Callable[[], bool] | None:
    """Return a platform-specific emergency stop predicate (Windows Esc key) if applicable."""
    mode = PlaybackMode(mode)
    if mode != PlaybackMode.WINDOWS or not is_windows_playback_available():
        return None
    from lyraforge.playback.windows import is_escape_pressed_win32

    return is_escape_pressed_win32
