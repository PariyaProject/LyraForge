"""Playback drivers.

M0 ships only ``DryRunDriver``: it records actions in memory and never sends
any OS input. A real Windows driver (M1) must implement the same protocol and
live in its own module so the core and tests never import Win32 APIs.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lyraforge.playback.clock import Clock


@runtime_checkable
class PlaybackDriver(Protocol):
    def key_down(self, key_id: str) -> None: ...

    def key_up(self, key_id: str) -> None: ...

    def release_all(self) -> list[str]:
        """Release every key this driver believes is pressed; return their ids."""
        ...


@dataclass(frozen=True, slots=True)
class DriverLogEntry:
    t_us: int
    action: str  # "down" | "up" | "release"
    key_id: str


class DryRunDriver:
    """Records key actions with clock timestamps. Sends nothing to the OS."""

    sends_os_input = False

    def __init__(self, clock: Clock):
        self._clock = clock
        self._lock = threading.Lock()
        self.log: list[DriverLogEntry] = []
        self.pressed: set[str] = set()

    def pressed_snapshot(self) -> list[str]:
        with self._lock:
            return sorted(self.pressed)

    def key_down(self, key_id: str) -> None:
        with self._lock:
            if key_id in self.pressed:  # defensive: never stack a second down
                self.pressed.discard(key_id)
                self.log.append(DriverLogEntry(self._clock.now_us(), "up", key_id))
            self.pressed.add(key_id)
            self.log.append(DriverLogEntry(self._clock.now_us(), "down", key_id))

    def key_up(self, key_id: str) -> None:
        with self._lock:
            if key_id not in self.pressed:
                return
            self.pressed.discard(key_id)
            self.log.append(DriverLogEntry(self._clock.now_us(), "up", key_id))

    def release_all(self) -> list[str]:
        with self._lock:
            released = sorted(self.pressed)
            for k in released:
                self.pressed.discard(k)
                self.log.append(DriverLogEntry(self._clock.now_us(), "release", k))
            return released
