"""Windows multimedia timer resolution guard (winmm timeBeginPeriod/timeEndPeriod)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress


@contextmanager
def high_resolution_timer(period_ms: int = 1) -> Iterator[None]:
    """Request 1 ms Windows scheduler timer resolution during active playback only."""
    if sys.platform != "win32" or period_ms <= 0:
        yield
        return
    winmm = None
    acquired = False
    try:
        import ctypes

        winmm = ctypes.WinDLL("winmm", use_last_error=False)
        res = int(winmm.timeBeginPeriod(int(period_ms)))
        acquired = res == 0
    except Exception:
        acquired = False
    try:
        yield
    finally:
        if acquired and winmm is not None:
            with suppress(Exception):
                winmm.timeEndPeriod(int(period_ms))
