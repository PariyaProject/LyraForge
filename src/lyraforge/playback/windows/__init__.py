"""Isolated Windows-only playback implementations.

This subpackage must NEVER be imported unconditionally by cross-platform core
modules. Call ``lyraforge.playback.factory.create_playback_backend`` instead.
"""

from lyraforge.playback.windows.driver import WindowsKeyboardDriver
from lyraforge.playback.windows.game_window import (
    DEFAULT_ALLOWED_PROCESSES,
    ForegroundWindowInfo,
    current_process_elevated,
    elevation_blocker,
    get_foreground_window_info,
    is_process_elevated,
    process_name_for_pid,
)
from lyraforge.playback.windows.win32_types import (
    KeyInputSpec,
    build_key_input_spec,
    is_escape_pressed_win32,
)
from lyraforge.playback.windows.window_guard import (
    DEFAULT_ALLOWED_TITLES,
    ForegroundWindowGuard,
)

__all__ = [
    "DEFAULT_ALLOWED_PROCESSES",
    "DEFAULT_ALLOWED_TITLES",
    "ForegroundWindowGuard",
    "ForegroundWindowInfo",
    "KeyInputSpec",
    "WindowsKeyboardDriver",
    "build_key_input_spec",
    "current_process_elevated",
    "elevation_blocker",
    "get_foreground_window_info",
    "is_escape_pressed_win32",
    "is_process_elevated",
    "process_name_for_pid",
]
