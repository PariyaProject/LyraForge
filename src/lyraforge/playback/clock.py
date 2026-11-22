"""Clocks for the playback scheduler (monotonic for real time, virtual for tests)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_us(self) -> int: ...

    def sleep_us(self, us: int) -> None: ...


class MonotonicClock:
    """Wall-clock based on ``time.monotonic_ns`` (never goes backwards)."""

    def now_us(self) -> int:
        return time.monotonic_ns() // 1000

    def sleep_us(self, us: int) -> None:
        if us > 0:
            time.sleep(us / 1_000_000)


class VirtualClock:
    """Deterministic clock: sleeping advances time instantly."""

    def __init__(self, start_us: int = 0):
        self._now = start_us

    def now_us(self) -> int:
        return self._now

    def sleep_us(self, us: int) -> None:
        if us > 0:
            self._now += us

    def advance(self, us: int) -> None:
        self._now += us
