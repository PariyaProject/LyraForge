"""Configurable global hotkeys for playback control.

Bindings are stored as text (for example ``Ctrl+Alt+F9``) and registered with the Windows
``RegisterHotKey`` API from one dedicated message-loop thread. Nothing is bound by
default; the user records/enters each shortcut explicitly. On non-Windows platforms the
registry reports that global hotkeys are unsupported instead of silently doing nothing.
"""

from __future__ import annotations

import queue
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from lyraforge.errors import ErrorCode, LyraError

HOTKEY_ACTIONS: tuple[str, ...] = ("start", "pause", "resume", "stop", "next", "previous")
ACTION_LABELS: dict[str, str] = {
    "start": "开始演奏",
    "pause": "暂停",
    "resume": "继续",
    "stop": "停止",
    "next": "下一首",
    "previous": "上一首",
}

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_VK: dict[str, int] = {
    **{f"F{i}": 0x6F + i for i in range(1, 25)},
    **{chr(0x41 + i): 0x41 + i for i in range(26)},
    **{str(i): 0x30 + i for i in range(10)},
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
}
_MOD_NAMES = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)


@dataclass(frozen=True, slots=True)
class HotkeyBinding:
    action: str
    modifiers: int
    vk: int
    display: str

    def to_json(self) -> dict[str, object]:
        return {
            "action": self.action,
            "text": self.display,
            "modifiers": self.modifiers,
            "vk": self.vk,
        }


def parse_hotkey(text: str) -> HotkeyBinding:
    """Parse ``Ctrl+Alt+F9`` into a binding; at least one modifier is required."""
    cleaned = text.replace(" ", "")
    parts = [part for part in cleaned.split("+") if part]
    if not parts:
        raise LyraError(ErrorCode.INVALID_ARGUMENT, "hotkey is empty")
    modifiers = 0
    key: str | None = None
    for part in parts:
        low = part.lower()
        if low in {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
        elif low == "alt":
            modifiers |= MOD_ALT
        elif low == "shift":
            modifiers |= MOD_SHIFT
        elif low in {"win", "meta"}:
            modifiers |= MOD_WIN
        elif key is None:
            key = part.upper()
        else:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, f"hotkey {text!r} has two keys")
    if modifiers == 0:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "hotkey must include at least one modifier (Ctrl/Alt/Shift/Win) "
            "to avoid swallowing game keys",
        )
    if key is None or key not in _VK:
        raise LyraError(ErrorCode.INVALID_ARGUMENT, f"unsupported hotkey key in {text!r}")
    display = "+".join([name for bit, name in _MOD_NAMES if modifiers & bit] + [key])
    return HotkeyBinding(action="", modifiers=modifiers, vk=_VK[key], display=display)


class HotkeyRegistry:
    """Registers text bindings on Windows and dispatches actions to callbacks."""

    def __init__(self, callbacks: Mapping[str, Callable[[], None]]) -> None:
        self._callbacks = dict(callbacks)
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._bindings: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def bindings(self) -> dict[str, str]:
        with self._lock:
            return dict(self._bindings)

    @property
    def errors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._errors)

    def supported(self) -> bool:
        return sys.platform == "win32"

    def apply(self, bindings: Mapping[str, str]) -> dict[str, str]:
        """Replace the active bindings; returns per-action registration errors."""
        self.stop()
        errors: dict[str, str] = {}
        parsed: list[tuple[str, HotkeyBinding]] = []
        for action, text in bindings.items():
            if action not in HOTKEY_ACTIONS:
                errors[action] = f"unknown hotkey action: {action}"
                continue
            if not text or not text.strip():
                continue
            try:
                parsed.append((action, parse_hotkey(text)))
            except LyraError as exc:
                errors[action] = exc.message
        if not parsed:
            with self._lock:
                self._bindings = {}
                self._errors = errors
            return errors
        if not self.supported():
            errors["_platform"] = "当前平台不支持全局热键（仅 Windows）"
            with self._lock:
                self._bindings = {}
                self._errors = errors
            return errors

        ready: queue.Queue[dict[str, str]] = queue.Queue()
        thread = threading.Thread(
            target=self._run,
            args=(parsed, ready),
            name="lyraforge-hotkeys",
            daemon=True,
        )
        thread.start()
        try:
            failures = ready.get(timeout=5.0)
        except queue.Empty:
            failures = {"_platform": "全局热键线程启动失败"}
        errors.update(failures)
        with self._lock:
            self._thread = thread
            self._bindings = {
                action: binding.display
                for action, binding in parsed
                if action not in failures
            }
            self._errors = errors
        return errors

    def _run(
        self, parsed: list[tuple[str, HotkeyBinding]], ready: queue.Queue[dict[str, str]]
    ) -> None:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        self._thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
        registered: dict[int, str] = {}
        failures: dict[str, str] = {}
        for index, (action, binding) in enumerate(parsed, start=1):
            if user32.RegisterHotKey(None, index, binding.modifiers, binding.vk):
                registered[index] = action
            else:
                failures[action] = f"{binding.display} 注册失败（可能已被其他程序占用）"
        ready.put(failures)

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                action = registered.get(int(msg.wParam))
                callback = self._callbacks.get(action) if action else None
                if callback is not None:
                    threading.Thread(target=callback, daemon=True).start()
        for index in registered:
            user32.UnregisterHotKey(None, index)

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if self._thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=2.0)
        with self._lock:
            self._thread = None
            self._thread_id = 0


__all__ = [
    "ACTION_LABELS",
    "HOTKEY_ACTIONS",
    "HotkeyBinding",
    "HotkeyRegistry",
    "parse_hotkey",
]
