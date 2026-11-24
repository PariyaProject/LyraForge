"""Public Win32 inspection of the foreground window, its process and elevation.

Only documented Win32 APIs are used (``GetForegroundWindow``,
``GetWindowThreadProcessId``, ``QueryFullProcessImageNameW``,
``OpenProcessToken``/``GetTokenInformation``). No game memory is read, no hooks are
installed and no process is modified.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_PROCESSES: tuple[str, ...] = ("GenshinImpact.exe", "YuanShen.exe")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20


@dataclass(frozen=True, slots=True)
class ForegroundWindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    elevated: bool | None


def _require_windows() -> None:
    if sys.platform != "win32":
        from lyraforge.errors import ErrorCode, LyraError

        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "foreground window inspection is only supported on Windows",
        )


_PID_NAME_CACHE: dict[int, str] = {}


def process_name_for_pid(pid: int) -> str:
    """Return the executable file name for ``pid`` (empty when it cannot be read)."""
    if pid <= 0:
        return ""
    cached = _PID_NAME_CACHE.get(pid)
    if cached is not None:
        return cached
    _require_windows()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        name = Path(buffer.value).name
        if len(_PID_NAME_CACHE) >= 64:
            _PID_NAME_CACHE.clear()
        _PID_NAME_CACHE[pid] = name
        return name
    finally:
        kernel32.CloseHandle(handle)


def is_process_elevated(pid: int) -> bool | None:
    """Return whether ``pid`` runs elevated, or ``None`` when it cannot be queried."""
    if pid <= 0:
        return None
    _require_windows()
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        # Access denied usually means the target has a higher integrity level.
        return None
    token = ctypes.c_void_p()
    try:
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        elevation = ctypes.c_ulong(0)
        returned = ctypes.c_ulong(0)
        ok = advapi32.GetTokenInformation(
            token,
            _TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        )
        return bool(elevation.value) if ok else None
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(handle)


def current_process_elevated() -> bool | None:
    return is_process_elevated(os.getpid())


def get_foreground_window_info(*, include_elevation: bool = True) -> ForegroundWindowInfo:
    """Return the foreground window's handle, PID, process name, title and elevation."""
    _require_windows()
    user32 = ctypes.windll.user32
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return ForegroundWindowInfo(0, 0, "", "", None)

    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    length = int(user32.GetWindowTextLengthW(hwnd))
    title = ""
    if length > 0:
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = str(buffer.value)
    process_name = process_name_for_pid(pid.value)
    elevated = (
        is_process_elevated(pid.value)
        if include_elevation and process_name
        else None
    )
    return ForegroundWindowInfo(hwnd, int(pid.value), process_name, title, elevated)


def elevation_blocker(target_elevated: bool | None, ours_elevated: bool | None) -> str | None:
    """Return an actionable message when UIPI would drop our synthetic input."""
    if ours_elevated:
        return None
    if target_elevated is True:
        return (
            "游戏以管理员身份运行，而 LyraForge 不是管理员；Windows 会丢弃低权限进程发送的按键。"
            "请以管理员身份重新启动 LyraForge 后再开始演奏。"
        )
    if target_elevated is None:
        return (
            "无法读取游戏进程的权限级别（通常意味着游戏以更高权限运行）。"
            "请以管理员身份重新启动 LyraForge 后再试。"
        )
    return None


__all__ = [
    "DEFAULT_ALLOWED_PROCESSES",
    "ForegroundWindowInfo",
    "current_process_elevated",
    "elevation_blocker",
    "get_foreground_window_info",
    "is_process_elevated",
    "process_name_for_pid",
]
