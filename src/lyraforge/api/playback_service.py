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
    PauseToken,
    PlaybackDriver,
    PlaybackMode,
    Player,
    StopToken,
    VirtualClock,
    create_emergency_stop_checker,
    create_playback_backend,
)

PREPARE_TOKEN_TTL_S = 60.0
DEFAULT_WAIT_FOR_FOCUS_S = 10.0
_FOCUS_POLL_S = 0.05


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
        self._pause_token: PauseToken | None = None
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
        effective_realtime = True if mode == PlaybackMode.WINDOWS else realtime
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
                realtime=effective_realtime,
                allowed_window_titles=titles,
                events=list(doc["events"]),
                profile=profile,
            )

        return {
            "prepare_token": token,
            "expires_in_s": int(PREPARE_TOKEN_TTL_S),
            "arrangement_id": arrangement_id,
            "mode": str(mode),
            "realtime": effective_realtime,
            "event_count": len(doc["events"]),
            "duration_ms": doc["duration_ms"],
            "calibration_status": profile.calibration_status,
            "sends_os_input": mode == PlaybackMode.WINDOWS,
            "risk_notice": (
                "Dry-run mode simulates playback internally and sends no OS keyboard events."
                if mode == PlaybackMode.DRY_RUN
                else "Windows keyboard simulation may violate game terms of service; "
                "ensure the in-game instrument UI is open and focused before starting. "
                "Press Esc or switch window focus to release keys immediately."
            ),
        }

    def start(
        self,
        prepare_token: str,
        *,
        data_dir: Path,
        wait_for_focus_s: float = DEFAULT_WAIT_FOR_FOCUS_S,
    ) -> dict[str, Any]:
        wait_s = max(0.0, min(30.0, float(wait_for_focus_s)))
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
            emergency_stop_fn = create_emergency_stop_checker(pending.mode)
            stop_token = StopToken()
            pause_token = PauseToken()
            session_id = str(uuid.uuid4())
            self._stop_token = stop_token
            self._pause_token = pause_token
            self._driver = driver
            self._state = "running" if pending.mode == PlaybackMode.DRY_RUN else "waiting_focus"
            self._session_id = session_id
            self._arrangement_id = pending.arrangement_id
            self._mode = pending.mode
            self._last_result = None

            def _finish(state: str, result: dict[str, Any] | None) -> None:
                with self._lock:
                    self._state = state
                    self._last_result = result
                    self._pause_token = None
                    self._thread = None

            def _run() -> None:
                try:
                    if not self._wait_for_focus(focus_guard, stop_token, wait_s):
                        if stop_token.stopped:
                            _finish(
                                "stopped",
                                {
                                    "state": "stopped",
                                    "stop_reason": stop_token.reason or "stopped_before_start",
                                },
                            )
                        else:
                            info = (
                                focus_guard.current_info()
                                if hasattr(focus_guard, "current_info")
                                else None
                            )
                            foreground = (
                                f"{info.process_name or '未知进程'} / {info.title or '无标题窗口'}"
                                if info is not None
                                else "未知前台窗口"
                            )
                            _finish(
                                "focus_timeout",
                                {
                                    "state": "focus_timeout",
                                    "error": (
                                        f"{wait_s:.0f} 秒内未检测到游戏窗口获得前台"
                                        f"（当前前台：{foreground}）。"
                                        "请切换到游戏后重新开始；未发送任何按键。"
                                    ),
                                },
                            )
                        return

                    problem = (
                        focus_guard.permission_problem()
                        if hasattr(focus_guard, "permission_problem")
                        else None
                    )
                    if problem:
                        _finish(
                            "permission_required",
                            {"state": "permission_required", "error": problem},
                        )
                        return

                    with self._lock:
                        if self._state != "paused":
                            self._state = "running"
                    player = Player(
                        driver,
                        clock,
                        focus_guard=focus_guard,
                        stop_token=stop_token,
                        pause_token=pause_token,
                        emergency_stop_fn=emergency_stop_fn,
                    )
                    result = player.play(pending.events)
                    if stop_token.reason not in {"library_restore", "server_shutdown"}:
                        try:
                            with LibraryStore(data_dir) as s:
                                mode_label = (
                                    f"{pending.mode}:"
                                    f"{'realtime' if pending.realtime else 'virtual'}"
                                )
                                s.record_playback_session(
                                    pending.arrangement_id,
                                    mode_label,
                                    result,
                                )
                        except Exception:  # pragma: no cover - defensive cleanup
                            pass
                    _finish(str(result.state), result.to_json())
                except Exception as exc:  # pragma: no cover - unexpected crash
                    _finish("error", {"state": "error", "error": f"{type(exc).__name__}: {exc}"})

            thread = threading.Thread(
                target=_run,
                name=f"lyraforge-playback-{session_id[:8]}",
                daemon=True,
            )
            self._thread = thread
            thread.start()

            return {
                "session_id": session_id,
                "status": self._state,
                "arrangement_id": pending.arrangement_id,
                "mode": str(pending.mode),
                "sends_os_input": bool(getattr(driver, "sends_os_input", False)),
                "wait_for_focus_s": wait_s,
            }

    @staticmethod
    def _wait_for_focus(guard: Any, stop_token: StopToken, seconds: float) -> bool:
        """Wait until the guard sees the game focused; ``False`` on timeout or stop."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if stop_token.stopped:
                return False
            if guard.is_target_focused():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_FOCUS_POLL_S)

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if (
                self._thread is None
                or not self._thread.is_alive()
                or self._pause_token is None
                or self._state not in {"waiting_focus", "running"}
            ):
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "no running playback session to pause")
            self._pause_token.pause()
            self._state = "paused"
        return self.status()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if (
                self._thread is None
                or not self._thread.is_alive()
                or self._pause_token is None
                or self._state != "paused"
            ):
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "no paused playback session to resume")
            self._pause_token.resume()
            self._state = "running"
        return self.status()

    def is_active(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def stop(self, reason: str = "user_api_stop", *, timeout_s: float = 3.0) -> dict[str, Any]:
        with self._lock:
            stop_token = self._stop_token
            pause_token = self._pause_token
            thread = self._thread
            self._pending = None
        if pause_token is not None:
            pause_token.resume()
        if stop_token is not None:
            stop_token.request_stop(reason)
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_s)))
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            snap_fn = getattr(self._driver, "pressed_snapshot", None)
            pressed = (
                snap_fn()
                if callable(snap_fn)
                else sorted(getattr(self._driver, "pressed", set()))
            )
            return {
                "state": self._state,
                "session_id": self._session_id,
                "arrangement_id": self._arrangement_id,
                "mode": str(self._mode) if self._mode is not None else None,
                "sends_os_input": bool(getattr(self._driver, "sends_os_input", False)),
                "keys_still_pressed": pressed,
                "last_result": self._last_result,
            }
