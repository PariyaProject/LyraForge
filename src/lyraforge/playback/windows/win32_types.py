"""Win32 SendInput keyboard structures and IBM Set 1 QWERTY scan codes.

Isolated inside ``lyraforge.playback.windows``. ``ctypes`` is imported lazily
only inside ``send_key_input_win32`` when running on ``win32``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from lyraforge.errors import ErrorCode, LyraError

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
VK_ESCAPE = 0x1B

QWERTY_SCAN_CODES: dict[str, int] = {
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "Q": 0x10,
    "W": 0x11,
    "E": 0x12,
    "R": 0x13,
    "T": 0x14,
    "Y": 0x15,
    "U": 0x16,
    "I": 0x17,
    "O": 0x18,
    "P": 0x19,
    "A": 0x1E,
    "S": 0x1F,
    "D": 0x20,
    "F": 0x21,
    "G": 0x22,
    "H": 0x23,
    "J": 0x24,
    "K": 0x25,
    "L": 0x26,
    "Z": 0x2C,
    "X": 0x2D,
    "C": 0x2E,
    "V": 0x2F,
    "B": 0x30,
    "N": 0x31,
    "M": 0x32,
}


@dataclass(frozen=True, slots=True)
class KeyInputSpec:
    """Platform-independent description of a single scan-code keyboard event."""

    binding: str
    scan_code: int
    flags: int

    @property
    def is_key_up(self) -> bool:
        return bool(self.flags & KEYEVENTF_KEYUP)


def build_key_input_spec(binding: str, *, key_up: bool) -> KeyInputSpec:
    """Convert an instrument key binding character into a Win32 scan-code spec."""
    norm = binding.strip().upper()
    scan = QWERTY_SCAN_CODES.get(norm)
    if scan is None:
        raise LyraError(
            ErrorCode.PROFILE_INVALID,
            f"unsupported keyboard binding for Win32 SendInput: {binding!r}",
            {"binding": binding},
        )
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    return KeyInputSpec(binding=norm, scan_code=scan, flags=flags)


@cache
def _win32_keyboard_api() -> tuple[Any, Any, Any, Any]:  # pragma: no cover - Windows-only OS call
    import ctypes
    from ctypes import wintypes

    ulong_ptr = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    class _INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", _INPUT_UNION),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return _INPUT, _INPUT_UNION, _KEYBDINPUT, user32


def send_key_inputs_win32(
    specs: Sequence[KeyInputSpec],
) -> None:  # pragma: no cover - Windows-only OS call
    """Atomically inject one or more scan-code events via Win32 ``SendInput``."""
    if sys.platform != "win32":
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "send_key_inputs_win32 is only supported on Windows",
        )
    if not specs:
        return
    import ctypes

    input_cls, union_cls, keybd_cls, user32 = _win32_keyboard_api()
    count = len(specs)
    arr = (input_cls * count)(
        *(
            input_cls(
                type=INPUT_KEYBOARD,
                union=union_cls(
                    ki=keybd_cls(
                        wVk=0,
                        wScan=spec.scan_code,
                        dwFlags=spec.flags,
                        time=0,
                        dwExtraInfo=0,
                    )
                ),
            )
            for spec in specs
        )
    )
    sent = user32.SendInput(count, arr, ctypes.sizeof(input_cls))
    if sent != count:
        err = ctypes.get_last_error()
        bindings = ",".join(s.binding for s in specs)
        raise OSError(
            f"Win32 SendInput failed for {bindings!r} (sent={sent}/{count}, win32_err={err})"
        )


def send_key_input_win32(spec: KeyInputSpec) -> None:  # pragma: no cover - Windows-only OS call
    """Send a single scan-code keyboard event via Win32 ``SendInput``."""
    if sys.platform != "win32":
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "send_key_input_win32 is only supported on Windows",
        )
    send_key_inputs_win32((spec,))


def is_escape_pressed_win32() -> bool:  # pragma: no cover - Windows-only OS call
    """Return True if the physical ESC key is currently down on Windows."""
    if sys.platform != "win32":
        return False
    _, _, _, user32 = _win32_keyboard_api()
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
