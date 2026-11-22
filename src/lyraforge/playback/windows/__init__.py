"""Isolated Windows-only playback implementations.

This subpackage must NEVER be imported unconditionally by cross-platform core
modules. Call ``lyraforge.playback.factory.create_playback_backend`` instead.
"""

from lyraforge.playback.windows.driver import WindowsKeyboardDriver
from lyraforge.playback.windows.win32_types import KeyInputSpec, build_key_input_spec
from lyraforge.playback.windows.window_guard import (
    DEFAULT_ALLOWED_TITLES,
    ForegroundWindowGuard,
)

__all__ = [
    "DEFAULT_ALLOWED_TITLES",
    "ForegroundWindowGuard",
    "KeyInputSpec",
    "WindowsKeyboardDriver",
    "build_key_input_spec",
]
