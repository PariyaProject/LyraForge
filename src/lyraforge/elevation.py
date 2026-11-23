"""Relaunch LyraForge with administrator privileges (Windows UAC).

Windows drops synthetic input sent by a lower-integrity process to a higher-integrity
window (UIPI), so when the game runs as administrator the desktop app must be relaunched
elevated. This module performs that user-initiated relaunch only; it never elevates
silently.
"""

from __future__ import annotations

import subprocess
import sys


def relaunch_elevated() -> bool:
    """Ask Windows to start a new elevated LyraForge instance; ``True`` when accepted."""
    if sys.platform != "win32":
        return False
    import ctypes

    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = ""
    else:
        executable = sys.executable
        params = subprocess.list2cmdline(["-m", "lyraforge.cli", "desktop"])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, None, 1
        )
    except OSError:
        return False
    return int(result) > 32


__all__ = ["relaunch_elevated"]
