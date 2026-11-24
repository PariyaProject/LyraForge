"""Windows SendInput PlaybackDriver implementation."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Sequence

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.playback.windows.win32_types import (
    KeyInputSpec,
    build_key_input_spec,
    send_key_input_win32,
    send_key_inputs_win32,
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
        send_batch_fn: Callable[[Sequence[KeyInputSpec]], None] | None = None,
        max_release_retries: int = 2,
    ) -> None:
        if send_input_fn is None and sys.platform != "win32":
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "WindowsKeyboardDriver requires Windows",
            )
        if max_release_retries < 0:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "max_release_retries must be non-negative",
            )
        self.profile = profile
        self._send = send_input_fn or send_key_input_win32
        self._send_batch = (
            send_batch_fn
            if send_batch_fn is not None
            else (send_key_inputs_win32 if send_input_fn is None else None)
        )
        self._max_release_retries = max_release_retries
        self._lock = threading.Lock()
        self.pressed: set[str] = set()

    def pressed_snapshot(self) -> list[str]:
        with self._lock:
            return sorted(self.pressed)

    def _binding_for(self, key_id: str) -> str:
        key_def = self.profile.key_by_id(key_id)
        if key_def is None:
            raise LyraError(
                ErrorCode.PROFILE_INVALID,
                f"unknown key_id {key_id!r} for profile {self.profile.id}",
            )
        return key_def.binding

    def _send_release_with_retry(self, spec: KeyInputSpec) -> None:
        last_exc: Exception | None = None
        for _attempt in range(self._max_release_retries + 1):
            try:
                self._send(spec)
                return
            except Exception as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    def key_down(self, key_id: str) -> None:
        with self._lock:
            binding = self._binding_for(key_id)
            if key_id in self.pressed:
                self._key_up_locked(key_id, binding)
            spec = build_key_input_spec(binding, key_up=False)
            self._send(spec)
            self.pressed.add(key_id)

    def key_down_batch(self, key_ids: Sequence[str]) -> None:
        if not key_ids:
            return
        if len(key_ids) == 1 or self._send_batch is None:
            for k in key_ids:
                self.key_down(k)
            return
        with self._lock:
            ordered_ids = list(dict.fromkeys(key_ids))
            specs: list[KeyInputSpec] = []
            for k in ordered_ids:
                binding = self._binding_for(k)
                if k in self.pressed:
                    self._key_up_locked(k, binding)
                specs.append(build_key_input_spec(binding, key_up=False))
            try:
                self._send_batch(specs)
            except Exception:
                # Conservatively mark keys so release_all() cleans up any partial OS batch delivery
                self.pressed.update(ordered_ids)
                raise
            self.pressed.update(ordered_ids)

    def _key_up_locked(self, key_id: str, binding: str) -> None:
        spec = build_key_input_spec(binding, key_up=True)
        self._send_release_with_retry(spec)
        # Update software state ONLY after OS key-up delivery succeeded
        self.pressed.discard(key_id)

    def key_up(self, key_id: str) -> None:
        with self._lock:
            if key_id not in self.pressed:
                return
            binding = self._binding_for(key_id)
            self._key_up_locked(key_id, binding)

    def key_up_batch(self, key_ids: Sequence[str]) -> None:
        if not key_ids:
            return
        if len(key_ids) == 1 or self._send_batch is None:
            for k in key_ids:
                self.key_up(k)
            return
        with self._lock:
            active = [k for k in dict.fromkeys(key_ids) if k in self.pressed]
            if not active:
                return
            bindings = [(k, self._binding_for(k)) for k in active]
            specs = [build_key_input_spec(b, key_up=True) for _, b in bindings]
            try:
                self._send_batch(specs)
                self.pressed.difference_update(active)
            except Exception:
                # Fall back to retried individual key_up so transient failures never stick keys
                for k, b in bindings:
                    self._key_up_locked(k, b)

    def release_all(self) -> list[str]:
        with self._lock:
            keys = sorted(self.pressed)
            released: list[str] = []
            errors: list[str] = []
            for k in keys:
                try:
                    binding = self._binding_for(k)
                    self._key_up_locked(k, binding)
                    released.append(k)
                except Exception as exc:
                    errors.append(f"{k}: {exc}")
            if errors:
                raise RuntimeError(f"failed releasing key(s): {'; '.join(errors)}")
            return released
