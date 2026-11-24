"""Clocks for the playback scheduler (monotonic for real time, virtual for tests)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now_us(self) -> int: ...

    def sleep_us(self, us: int) -> None: ...


class MonotonicClock:
    """Wall-clock based on ``time.monotonic_ns`` with two-tier hybrid sleep."""

    def now_us(self) -> int:
        return time.monotonic_ns() // 1000

    def sleep_coarse_us(self, us: int) -> None:
        """Pure OS sleep used for intermediate idle poll chunks without busy-wait CPU."""
        if us > 0:
            time.sleep(us / 1_000_000)

    def sleep_us(self, us: int) -> None:
        if us <= 0:
            return
        target_ns = time.monotonic_ns() + us * 1000
        # Coarse sleep down to ~2 ms before deadline, yield down to ~0.4 ms,
        # and spin only for the final sub-millisecond tail for tight onset accuracy.
        now_ns = time.monotonic_ns()
        coarse_s = (target_ns - 2_000_000 - now_ns) / 1_000_000_000
        if coarse_s > 0.0005:
            time.sleep(coarse_s)
        while time.monotonic_ns() < target_ns - 400_000:
            time.sleep(0)
        while time.monotonic_ns() < target_ns:
            pass


class VirtualClock:
    """Deterministic clock: sleeping advances time instantly."""

    def __init__(self, start_us: int = 0):
        self._now = start_us

    def now_us(self) -> int:
        return self._now

    def sleep_coarse_us(self, us: int) -> None:
        # Delegate through sleep_us so subclasses (e.g. test Stop/Advance clocks) still run.
        self.sleep_us(us)

    def sleep_us(self, us: int) -> None:
        if us > 0:
            self._now += us

    def advance(self, us: int) -> None:
        self._now += us
