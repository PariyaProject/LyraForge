"""Clocks for the playback scheduler (monotonic for real time, virtual for tests)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_us(self) -> int: ...

    def sleep_us(self, us: int) -> None: ...


class MonotonicClock:
    """Wall-clock based on ``time.monotonic_ns`` with hybrid precision sleep."""

    def now_us(self) -> int:
        return time.monotonic_ns() // 1000

    def sleep_us(self, us: int) -> None:
        if us <= 0:
            return
        target_ns = time.monotonic_ns() + us * 1000
        # Reserve the final ~1.5 ms for monotonic busy-wait so OS timer coarseness
        # does not skew chord/rhythm precision.
        coarse_s = (us - 1500) / 1_000_000
        if coarse_s > 0.0005:
            time.sleep(coarse_s)
        while time.monotonic_ns() < target_ns:
            pass


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
