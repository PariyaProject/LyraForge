"""Windows SendInput PlaybackDriver implementation."""

from __future__ import annotations

import sys
from collections.abc import Callable

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.playback.windows.win32_types import (
    KeyInputSpec,
    build_key_input_spec,
    send_key_input_win32,
)


class WindowsKeyboardDriver:
    """Simulated keyboard driver targeting Windows foreground applications.

    Never reads or injects game memory. Only sends standard keyboard scan-code
    events via ``SendInput`` and tracks pressed keys so ``release_all()`` clears
    every held key on any exit path.
    """

    sends_os_input = True

    def __init__(
        self,
        profile: InstrumentProfile,
        *,
        send_input_fn: Callable[[KeyInputSpec], None] | None = None,
    ) -> None:
        if send_input_fn is None and sys.platform != "win32":
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "WindowsKeyboardDriver requires Windows",
            )
        self.profile = profile
        self._send = send_input_fn or send_key_input_win32
        self.pressed: set[str] = set()

    def _binding_for(self, key_id: str) -> str:
        key_def = self.profile.key_by_id(key_id)
        if key_def is None:
            raise LyraError(
                ErrorCode.PROFILE_INVALID,
                f"unknown key_id {key_id!r} for profile {self.profile.id}",
            )
        return key_def.binding

    def key_down(self, key_id: str) -> None:
        binding = self._binding_for(key_id)
        if key_id in self.pressed:
            self.key_up(key_id)
        spec = build_key_input_spec(binding, key_up=False)
        self._send(spec)
        self.pressed.add(key_id)

    def key_up(self, key_id: str) -> None:
        if key_id not in self.pressed:
            return
        binding = self._binding_for(key_id)
        self.pressed.discard(key_id)
        spec = build_key_input_spec(binding, key_up=True)
        self._send(spec)

    def release_all(self) -> list[str]:
        keys = sorted(self.pressed)
        released: list[str] = []
        errors: list[str] = []
        for k in keys:
            try:
                self.key_up(k)
                released.append(k)
            except Exception as exc:
                errors.append(f"{k}: {exc}")
        if errors:
            raise RuntimeError(f"failed releasing key(s): {'; '.join(errors)}")
        return released
