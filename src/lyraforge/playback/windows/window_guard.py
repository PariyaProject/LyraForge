"""Windows foreground window guard using public Win32 window APIs only."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from lyraforge.errors import ErrorCode, LyraError

DEFAULT_ALLOWED_TITLES: tuple[str, ...] = ("Genshin Impact", "原神")


def get_foreground_window_title_win32() -> str:  # pragma: no cover - Windows-only OS call
    """Return the active Win32 foreground window title without touching process memory."""
    if sys.platform != "win32":
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "get_foreground_window_title_win32 is only supported on Windows",
        )
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return str(buf.value)


class ForegroundWindowGuard:
    """Fail-closed focus guard matching foreground window title against an allowlist."""

    def __init__(
        self,
        allowed_titles: Sequence[str] = DEFAULT_ALLOWED_TITLES,
        *,
        get_title_fn: Callable[[], str] | None = None,
    ) -> None:
        if get_title_fn is None and sys.platform != "win32":
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "ForegroundWindowGuard requires Windows",
            )
        cleaned = tuple(t.strip() for t in allowed_titles if t.strip())
        if not cleaned:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "ForegroundWindowGuard requires at least one non-empty allowed window title",
            )
        self.allowed_titles = cleaned
        self._get_title = get_title_fn or get_foreground_window_title_win32

    def is_target_focused(self) -> bool:
        try:
            title = self._get_title()
        except Exception:
            return False
        low = title.lower()
        return any(allowed.lower() in low for allowed in self.allowed_titles)
