"""Windows foreground window guard using public Win32 window APIs only."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.playback.windows.game_window import (
    DEFAULT_ALLOWED_PROCESSES,
    ForegroundWindowInfo,
    current_process_elevated,
    elevation_blocker,
    get_foreground_window_info,
)

DEFAULT_ALLOWED_TITLES: tuple[str, ...] = ("Genshin Impact", "原神")


def get_foreground_window_title_win32() -> str:  # pragma: no cover - Windows-only OS call
    """Return the active Win32 foreground window title without touching process memory."""
    if sys.platform != "win32":
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "get_foreground_window_title_win32 is only supported on Windows",
        )
    return get_foreground_window_info().title


class ForegroundWindowGuard:
    """Fail-closed guard matching the foreground window's process name and title.

    The process name (``GenshinImpact.exe`` / ``YuanShen.exe``) is the primary signal so
    localized titles, fullscreen modes and renamed windows cannot break playback. Title
    matching remains as a fallback and for existing tests/diagnostics.
    """

    def __init__(
        self,
        allowed_titles: Sequence[str] = DEFAULT_ALLOWED_TITLES,
        *,
        allowed_processes: Sequence[str] = (),
        get_title_fn: Callable[[], str] | None = None,
        get_info_fn: Callable[[], ForegroundWindowInfo] | None = None,
    ) -> None:
        if get_info_fn is None and get_title_fn is None and sys.platform != "win32":
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "ForegroundWindowGuard requires Windows",
            )
        cleaned_titles = tuple(t.strip() for t in allowed_titles if t.strip())
        cleaned_processes = tuple(p.strip().lower() for p in allowed_processes if p.strip())
        if not cleaned_titles and not cleaned_processes:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "ForegroundWindowGuard requires at least one non-empty allowed title or process",
            )
        self.allowed_titles = cleaned_titles
        self.allowed_processes = cleaned_processes
        self._get_title = get_title_fn
        self._get_info = get_info_fn

    def current_info(self) -> ForegroundWindowInfo | None:
        """Return the current foreground window info, or ``None`` when unavailable."""
        if self._get_info is not None:
            try:
                return self._get_info()
            except Exception:
                return None
        if self._get_title is not None:
            try:
                return ForegroundWindowInfo(0, 0, "", self._get_title(), None)
            except Exception:
                return None
        try:
            return get_foreground_window_info()
        except Exception:
            return None

    def _title_matches(self, title: str) -> bool:
        low = title.lower()
        return any(allowed.lower() in low for allowed in self.allowed_titles)

    def is_target_focused(self) -> bool:
        info = self.current_info()
        if info is None:
            return False
        if info.process_name and info.process_name.lower() in self.allowed_processes:
            return True
        return self._title_matches(info.title)

    def permission_problem(self) -> str | None:
        """Return an actionable message when Windows would drop our synthetic input."""
        info = self.current_info()
        target_elevated = info.elevated if info is not None else None
        return elevation_blocker(target_elevated, current_process_elevated())


__all__ = ["DEFAULT_ALLOWED_PROCESSES", "DEFAULT_ALLOWED_TITLES", "ForegroundWindowGuard"]
