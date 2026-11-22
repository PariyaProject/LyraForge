"""Stop token and focus guard abstractions.

The real ``ForegroundWindowGuard`` (M1) will check the foreground window via
public Win32 window APIs only; it must never read or touch game memory.
"""

from __future__ import annotations

import threading
from typing import Protocol


class FocusGuard(Protocol):
    def is_target_focused(self) -> bool: ...


class NullFocusGuard:
    """For dry-run: there is no target window, so focus is always 'ok'."""

    def is_target_focused(self) -> bool:
        return True


class StopToken:
    """Thread-safe cooperative stop flag (UI stop button, hotkey, Ctrl+C)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: str | None = None

    def request_stop(self, reason: str = "user") -> None:
        if not self._event.is_set():
            self.reason = reason
            self._event.set()

    @property
    def stopped(self) -> bool:
        return self._event.is_set()
