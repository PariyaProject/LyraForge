"""Playback layer: scheduler, drivers, guards, calibration.

M0 contains no OS input implementation. Importing this package never imports
Win32/ctypes; see tests/unit/test_layering.py.
"""

from lyraforge.playback.calibration import (
    CALIBRATION_PATTERNS,
    CalibrationPattern,
    analyze_calibration_recording,
    build_calibration_performance,
    get_calibration_pattern,
    list_calibration_patterns,
    run_calibration_benchmark,
)
from lyraforge.playback.clock import Clock, MonotonicClock, VirtualClock
from lyraforge.playback.driver import DriverLogEntry, DryRunDriver, PlaybackDriver
from lyraforge.playback.factory import (
    PlaybackMode,
    create_emergency_stop_checker,
    create_playback_backend,
    is_windows_playback_available,
)
from lyraforge.playback.guards import FocusGuard, NullFocusGuard, PauseToken, StopToken
from lyraforge.playback.player import (
    KeyAction,
    LateEventPolicy,
    PlaybackOptions,
    PlaybackResult,
    PlaybackState,
    Player,
    expand_events,
    expand_events_with_stats,
)

__all__ = [
    "CALIBRATION_PATTERNS",
    "CalibrationPattern",
    "Clock",
    "DriverLogEntry",
    "DryRunDriver",
    "FocusGuard",
    "KeyAction",
    "LateEventPolicy",
    "MonotonicClock",
    "NullFocusGuard",
    "PauseToken",
    "PlaybackDriver",
    "PlaybackMode",
    "PlaybackOptions",
    "PlaybackResult",
    "PlaybackState",
    "Player",
    "StopToken",
    "VirtualClock",
    "analyze_calibration_recording",
    "build_calibration_performance",
    "create_emergency_stop_checker",
    "create_playback_backend",
    "expand_events",
    "expand_events_with_stats",
    "get_calibration_pattern",
    "is_windows_playback_available",
    "list_calibration_patterns",
    "run_calibration_benchmark",
]
