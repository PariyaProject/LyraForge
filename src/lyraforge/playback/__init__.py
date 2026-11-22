"""Playback layer: scheduler, drivers, guards.

M0 contains no OS input implementation. Importing this package never imports
Win32/ctypes; see tests/unit/test_layering.py.
"""

from lyraforge.playback.clock import Clock, MonotonicClock, VirtualClock
from lyraforge.playback.driver import DriverLogEntry, DryRunDriver, PlaybackDriver
from lyraforge.playback.factory import (
    PlaybackMode,
    create_playback_backend,
    is_windows_playback_available,
)
from lyraforge.playback.guards import FocusGuard, NullFocusGuard, StopToken
from lyraforge.playback.player import (
    KeyAction,
    PlaybackResult,
    PlaybackState,
    Player,
    expand_events,
)

__all__ = [
    "Clock",
    "DriverLogEntry",
    "DryRunDriver",
    "FocusGuard",
    "KeyAction",
    "MonotonicClock",
    "NullFocusGuard",
    "PlaybackDriver",
    "PlaybackMode",
    "PlaybackResult",
    "PlaybackState",
    "Player",
    "StopToken",
    "VirtualClock",
    "create_playback_backend",
    "expand_events",
    "is_windows_playback_available",
]
