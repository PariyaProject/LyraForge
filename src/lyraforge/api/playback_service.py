"""Thread-safe playback manager enforcing explicit prepare->start authorization."""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import load_builtin_profile
from lyraforge.library import LibraryStore
from lyraforge.music_core.performance import validate_performance
from lyraforge.music_core.profile import InstrumentProfile
from lyraforge.playback import (
    MonotonicClock,
    PlaybackDriver,
    PlaybackMode,
    Player,
    StopToken,
    VirtualClock,
    create_playback_backend,
)

PREPARE_TOKEN_TTL_S = 60.0


@dataclass(slots=True)
class _PendingPrepare:
    token: str
    expires_mono: float
    arrangement_id: str
    mode: PlaybackMode
    realtime: bool
    allowed_window_titles: tuple[str, ...] | None
    events: list[dict[str, Any]]
    profile: InstrumentProfile


class PlaybackManager:
    """Coordinates explicit prepare -> start -> stop lifecycle for one active session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: _PendingPrepare | None = None
        self._thread: threading.Thread | None = None
        self._stop_token: StopToken | None = None
        self._driver: PlaybackDriver | None = None
        self._state: str = "idle"
        self._session_id: str | None = None
        self._arrangement_id: str | None = None
        self._mode: PlaybackMode | None = None
        self._last_result: dict[str, Any] | None = None

    def prepare(
        self,
        arrangement_id: str,
        *,
        mode: PlaybackMode = PlaybackMode.DRY_RUN,
        realtime: bool = False,
        allowed_window_titles: Sequence[str] | None = None,
        store: LibraryStore,
    ) -> dict[str, Any]:
        mode = PlaybackMode(mode)
        doc = store.load_arrangement_performance(arrangement_id)
        profile = load_builtin_profile(str(doc["instrument_profile_id"]))
        validate_performance(doc, profile)

        # Verify backend compatibility on the current OS before issuing a token.
        titles = tuple(allowed_window_titles) if allowed_window_titles else None
        create_playback_backend(
            mode,
            profile=profile,
            clock=VirtualClock(),
            allowed_window_titles=titles,
        )

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise LyraError(
                    ErrorCode.PLAYBACK_ABORTED,
                    "playback is already running; stop it before preparing another",
                )
            token = secrets.token_urlsafe(24)
            self._pending = _PendingPrepare(
                token=token,
                expires_mono=time.monotonic() + PREPARE_TOKEN_TTL_S,
                arrangement_id=arrangement_id,
                mode=mode,
                realtime=realtime,
                allowed_window_titles=titles,
                events=list(doc["events"]),
                profile=profile,
            )

        return {
            "prepare_token": token,
            "expires_in_s": int(PREPARE_TOKEN_TTL_S),
            "arrangement_id": arrangement_id,
            "mode": str(mode),
            "realtime": realtime,
            "event_count": len(doc["events"]),
            "duration_ms": doc["duration_ms"],
            "calibration_status": profile.calibration_status,
            "sends_os_input": mode == PlaybackMode.WINDOWS,
            "risk_notice": (
                "Dry-run mode simulates playback internally and sends no OS keyboard events."
                if mode == PlaybackMode.DRY_RUN
                else "Windows keyboard simulation may violate game terms of service; "
                "ensure the in-game instrument UI is open and focused before starting."
            ),
        }

    def start(self, prepare_token: str, *, data_dir: Path) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise LyraError(
                    ErrorCode.PLAYBACK_ABORTED,
                    "playback is already running",
                )
            pending = self._pending
            if (
                pending is None
                or not secrets.compare_digest(pending.token, prepare_token)
                or time.monotonic() > pending.expires_mono
            ):
                raise LyraError(
                    ErrorCode.PERMISSION_REQUIRED,
                    "invalid, expired, or already-used prepare_token",
                )
            self._pending = None

            clock = MonotonicClock() if pending.realtime else VirtualClock()
            driver, focus_guard = create_playback_backend(
                pending.mode,
                profile=pending.profile,
                clock=clock,
                allowed_window_titles=pending.allowed_window_titles,
            )
            stop_token = StopToken()
            session_id = str(uuid.uuid4())
            self._stop_token = stop_token
            self._driver = driver
            self._state = "running"
            self._session_id = session_id
            self._arrangement_id = pending.arrangement_id
            self._mode = pending.mode
            self._last_result = None

            def _run() -> None:
                player = Player(
                    driver,
                    clock,
                    focus_guard=focus_guard,
                    stop_token=stop_token,
                )
                result = player.play(pending.events)
                try:
                    with LibraryStore(data_dir) as s:
                        s.record_playback_session(
                            pending.arrangement_id,
                            f"{pending.mode}:{'realtime' if pending.realtime else 'virtual'}",
                            result,
                        )
                except Exception:  # pragma: no cover - defensive cleanup
                    pass
                with self._lock:
                    self._state = str(result.state)
                    self._last_result = result.to_json()
                    self._thread = None

            thread = threading.Thread(
                target=_run,
                name=f"lyraforge-playback-{session_id[:8]}",
                daemon=True,
            )
            self._thread = thread
            thread.start()

            return {
                "session_id": session_id,
                "status": "running",
                "arrangement_id": pending.arrangement_id,
                "mode": str(pending.mode),
                "sends_os_input": bool(getattr(driver, "sends_os_input", False)),
            }

    def stop(self, reason: str = "user_api_stop") -> dict[str, Any]:
        with self._lock:
            stop_token = self._stop_token
            thread = self._thread
            self._pending = None
        if stop_token is not None:
            stop_token.request_stop(reason)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            pressed = sorted(getattr(self._driver, "pressed", set()))
            return {
                "state": self._state,
                "session_id": self._session_id,
                "arrangement_id": self._arrangement_id,
                "mode": str(self._mode) if self._mode is not None else None,
                "sends_os_input": bool(getattr(self._driver, "sends_os_input", False)),
                "keys_still_pressed": pressed,
                "last_result": self._last_result,
            }
