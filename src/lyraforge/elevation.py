"""Administrator privilege helpers for the Windows desktop application.

Windows drops synthetic input sent by a lower-integrity process to a higher-integrity
window (UIPI), so running LyraForge as administrator matches games launched elevated
while still allowing explicit user opt-out via ``--no-elevate`` or
``LYRAFORGE_NO_ELEVATE=1``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

NO_ELEVATE_ENV = "LYRAFORGE_NO_ELEVATE"


def is_current_process_elevated() -> bool:
    """Return ``True`` when running elevated on Windows; ``False`` elsewhere."""
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _source_gui_python() -> str:
    """Prefer windowless ``pythonw.exe`` on Windows when relaunching from source."""
    current = Path(sys.executable)
    pythonw = current.with_name("pythonw.exe")
    return str(pythonw) if pythonw.is_file() else sys.executable


def relaunch_elevated(extra_args: Sequence[str] = ()) -> bool:
    """Ask Windows UAC to start an elevated LyraForge instance; ``True`` if accepted."""
    if sys.platform != "win32":
        return False
    import ctypes

    args_list = [str(arg) for arg in extra_args]
    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = subprocess.list2cmdline(args_list) if args_list else ""
    else:
        executable = _source_gui_python()
        params = subprocess.list2cmdline(["-m", "lyraforge.cli", "desktop", *args_list])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, None, 1
        )
    except (AttributeError, OSError):
        return False
    return int(result) > 32


def maybe_elevate_for_desktop(argv_args: Sequence[str] = (), *, disabled: bool = False) -> bool:
    """Elevate on Windows GUI launch unless disabled, opted out, or already admin."""
    if sys.platform != "win32" or disabled:
        return False
    if os.environ.get(NO_ELEVATE_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return False
    if is_current_process_elevated():
        return False
    forwarded = [str(arg) for arg in argv_args]
    if "--no-elevate" not in forwarded:
        forwarded.append("--no-elevate")
    return relaunch_elevated(forwarded)


__all__ = [
    "NO_ELEVATE_ENV",
    "is_current_process_elevated",
    "maybe_elevate_for_desktop",
    "relaunch_elevated",
]
