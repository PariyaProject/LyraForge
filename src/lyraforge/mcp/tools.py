"""Typed MCP tool definitions, task/cancellation registry, and LyraForge dispatchers."""

from __future__ import annotations

import inspect
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes, resolve_under
from lyraforge.instruments import DEFAULT_PROFILE_ID, load_builtin_profile
from lyraforge.library.packaging import export_lyrapack
from lyraforge.library.store import LibraryStore
from lyraforge.music_core import (
    ArrangeOptions,
    evaluate_events_against_reference,
    evaluate_transcription_against_reference,
    load_midi_file,
)
from lyraforge.music_core.arranger import SemitonePolicy, Style
from lyraforge.playback.guards import StopToken
from lyraforge.secrets import redact_secret
from lyraforge.sources.local import LocalLibrarySourceAdapter
from lyraforge.sources.online import OpenMusicCatalogSourceAdapter, rank_candidates
from lyraforge.sources.url import DirectUrlSourceAdapter
from lyraforge.transcribers import DEFAULT_TRANSCRIBER_ID, TranscribeOptions


@dataclass
class MCPTaskRecord:
    task_id: str
    tool: str
    status: str = "queued"  # queued | running | completed | failed | cancelled
    progress: float = 0.0
    logs: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    stop_token: StopToken = field(default_factory=StopToken)
    finished: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool": self.tool,
            "status": self.status,
            "progress": round(self.progress, 4),
            "logs": list(self.logs[-50:]),
            "error": self.error,
            "finished": self.finished,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MCPTaskRegistry:
    """Thread-safe task status, progress log, and non-evicting active cancellation store."""

    def __init__(self, max_tasks: int = 100) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, MCPTaskRecord] = {}
        self._request_to_task: dict[str, str] = {}
        self._pre_cancelled: dict[str, str] = {}
        self._max_tasks = max(1, int(max_tasks))

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for rec in self._tasks.values() if not rec.finished)

    def create(
        self,
        tool: str,
        *,
        task_id: str | None = None,
        request_id: str | int | None = None,
        stop_token: StopToken | None = None,
    ) -> MCPTaskRecord:
        with self._lock:
            tid = (task_id or "").strip() or f"mcp-{uuid.uuid4().hex[:10]}"
            existing = self._tasks.get(tid)
            if existing is not None:
                if not existing.finished:
                    raise LyraError(
                        ErrorCode.INVALID_ARGUMENT, f"task_id {tid!r} is already active"
                    )
                stale_old = [
                    rk for rk, mapped in self._request_to_task.items() if mapped == tid
                ]
                for rk in stale_old:
                    del self._request_to_task[rk]
            else:
                self._reclaim_finished_locked(max_remaining=self._max_tasks - 1)
                if len(self._tasks) >= self._max_tasks:
                    active = sum(1 for v in self._tasks.values() if not v.finished)
                    raise LyraError(
                        ErrorCode.LIMIT_EXCEEDED,
                        f"MCP task registry capacity reached ({self._max_tasks} active tasks); "
                        "retry after an active task finishes",
                        {"max_tasks": self._max_tasks, "active_tasks": active},
                    )

            token = stop_token or StopToken()
            rec = MCPTaskRecord(
                task_id=tid,
                tool=tool,
                status="running",
                progress=0.0,
                stop_token=token,
                finished=False,
            )
            rec.logs.append(f"[{tool}] started")

            cancel_reason: str | None = self._pre_cancelled.pop(tid, None)
            if request_id is not None:
                req_reason = self._pre_cancelled.pop(str(request_id), None)
                if cancel_reason is None:
                    cancel_reason = req_reason
                self._request_to_task[str(request_id)] = tid
            if cancel_reason is not None:
                rec.stop_token.request_stop(cancel_reason)
                rec.status = "cancelled"
                rec.finished = True
                rec.logs.append("cancelled prior to execution")
            elif rec.stop_token.stopped:
                rec.status = "cancelled"
                rec.finished = True
                rec.logs.append("cancelled prior to execution")

            self._tasks[tid] = rec
            return rec

    def _reclaim_finished_locked(self, *, max_remaining: int) -> None:
        """Evict only finished tasks cleanly; never evict running/queued active tasks."""
        while len(self._tasks) > max_remaining:
            evict_id = next(
                (k for k, v in self._tasks.items() if v.finished),
                None,
            )
            if evict_id is None:
                break
            del self._tasks[evict_id]
            stale_reqs = [rk for rk, mapped in self._request_to_task.items() if mapped == evict_id]
            for rk in stale_reqs:
                del self._request_to_task[rk]

    def log(self, task_id: str, progress: float, message: str) -> None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                return
            rec.progress = max(0.0, min(1.0, float(progress)))
            rec.logs.append(message)
            rec.updated_at = datetime.now(UTC).isoformat()

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        progress: float | None = None,
        message: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                return
            rec.status = status
            rec.finished = True
            if progress is not None:
                rec.progress = max(0.0, min(1.0, float(progress)))
            if message:
                rec.logs.append(message)
            rec.error = error
            rec.updated_at = datetime.now(UTC).isoformat()
            self._pre_cancelled.pop(task_id, None)
            for rk, mapped in self._request_to_task.items():
                if mapped == task_id:
                    self._pre_cancelled.pop(rk, None)

    def cancel(self, target_id: str) -> MCPTaskRecord | None:
        with self._lock:
            key = str(target_id)
            tid = self._request_to_task.get(key, key)
            rec = self._tasks.get(tid)
            if rec is None:
                self._pre_cancelled[key] = f"cancelled via MCP ({key})"
                max_pre = max(16, self._max_tasks * 4)
                while len(self._pre_cancelled) > max_pre:
                    oldest_pre = next(iter(self._pre_cancelled))
                    del self._pre_cancelled[oldest_pre]
                return None
            if not rec.finished:
                rec.stop_token.request_stop(f"cancelled via MCP ({key})")
                rec.status = "cancelled"
                rec.logs.append("cancellation requested")
                rec.updated_at = datetime.now(UTC).isoformat()
            return rec

    def is_pre_cancelled(self, target_id: str) -> bool:
        with self._lock:
            return str(target_id) in self._pre_cancelled

    def consume_pre_cancel(self, target_id: str) -> str | None:
        with self._lock:
            return self._pre_cancelled.pop(str(target_id), None)

    def cancel_all(self, reason: str = "shutdown") -> int:
        cancelled = 0
        with self._lock:
            for rec in self._tasks.values():
                if not rec.finished:
                    rec.stop_token.request_stop(reason)
                    rec.status = "cancelled"
                    rec.logs.append(f"cancelled ({reason})")
                    rec.updated_at = datetime.now(UTC).isoformat()
                    cancelled += 1
        return cancelled

    def get(self, task_id: str) -> MCPTaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._tasks.values())[-limit:]
            return [r.to_json() for r in reversed(items)]


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_music",
        "description": (
            "Search local LyraForge library, configured user folders, and optionally "
            "open-licensed Internet Archive items (requires allow_network=true)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song title, keyword, or composer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "allow_network": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicitly allow querying Internet Archive open catalog.",
                },
                "task_id": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "import_media",
        "description": (
            "Import a local MIDI/audio/video file or user-authorized public HTTP(S) URL "
            "into the LyraForge library (cancellation aborts before database commit)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local MIDI, WAV, MP3, MP4, or MKV path"},
                "url": {
                    "type": "string",
                    "description": "Public HTTP(S) URL when importing remote",
                },
                "title": {"type": "string"},
                "artist": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "allow_network": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true to download from a remote URL.",
                },
                "task_id": {"type": "string"},
            },
        },
    },
    {
        "name": "transcribe",
        "description": (
            "Transcribe an imported audio/video song in the library to MIDI using direct or "
            "Demucs vocal-separation pipelines (never silently falls back to mono accompaniment)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "string"},
                "pipeline_id": {
                    "type": "string",
                    "enum": [
                        "direct",
                        "vocal_split_full",
                        "vocal_split_lead",
                        "vocal_split_accomp",
                    ],
                    "default": "direct",
                },
                "engine_id": {"type": "string", "default": DEFAULT_TRANSCRIBER_ID},
                "vocal_engine_id": {"type": "string"},
                "accomp_engine_id": {"type": "string"},
                "vocal_cleanup": {
                    "type": "string",
                    "enum": ["off", "light", "standard", "strong"],
                    "default": "standard",
                },
                "vocal_range": {
                    "type": "string",
                    "enum": ["auto", "male", "female"],
                    "default": "auto",
                },
                "min_pitch": {"type": "integer", "minimum": 0, "maximum": 126, "default": 36},
                "max_pitch": {"type": "integer", "minimum": 1, "maximum": 127, "default": 96},
                "min_note_ms": {"type": "integer", "minimum": 10, "default": 60},
                "task_id": {"type": "string"},
            },
            "required": ["song_id"],
        },
    },
    {
        "name": "arrange",
        "description": (
            "Arrange a song (from MIDI source or chosen transcription) for a Genshin Impact "
            "instrument profile using classic or vocal_lead strategy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "string"},
                "profile_id": {"type": "string", "default": DEFAULT_PROFILE_ID},
                "transcription_id": {"type": "string"},
                "arranger_strategy": {
                    "type": "string",
                    "enum": ["classic", "vocal_lead", "vocal_dynamic"],
                    "default": "classic",
                },
                "melody_track": {"type": "integer", "minimum": 0},
                "include_tracks": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                "vocal_ducking": {"type": "boolean", "default": True},
                "melody_ceiling": {"type": "boolean", "default": True},
                "anti_clash_semitones": {"type": "boolean", "default": True},
                "accomp_density": {
                    "type": "string",
                    "enum": ["auto", "minimal", "balanced", "full"],
                },
                "phrase_octave_mode": {
                    "type": "string",
                    "enum": ["original", "smooth_lift", "centered"],
                },
                "cross_stem_align_ms": {"type": "integer", "minimum": 0, "maximum": 60},
                "style": {
                    "type": "string",
                    "enum": [s.value for s in Style],
                    "default": Style.BALANCED.value,
                },
                "transpose": {"type": "integer", "minimum": -48, "maximum": 48},
                "semitone_policy": {
                    "type": "string",
                    "enum": [p.value for p in SemitonePolicy],
                    "default": SemitonePolicy.NEAREST.value,
                },
                "speed": {"type": "number", "minimum": 0.25, "maximum": 4.0, "default": 1.0},
                "max_chord_keys": {"type": "integer", "minimum": 1, "maximum": 32},
                "chord_window_ms": {"type": "integer", "minimum": 0, "maximum": 200, "default": 20},
                "arpeggiate_ms": {"type": "integer", "minimum": 0, "maximum": 60, "default": 0},
                "timing_mode": {
                    "type": "string",
                    "enum": ["adapted", "strict_fidelity"],
                    "default": "adapted",
                },
                "label": {"type": "string"},
                "task_id": {"type": "string"},
            },
            "required": ["song_id"],
        },
    },
    {
        "name": "evaluate",
        "description": (
            "Evaluate arrangement playability (vs input MIDI), optional A/B comparison, "
            "and optional ground-truth fidelity against a reference MIDI."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "arrangement_id": {"type": "string"},
                "compare_with_arrangement_id": {"type": "string"},
                "reference_midi_path": {
                    "type": "string",
                    "description": "Optional ground-truth MIDI path for end-to-end recall/F1.",
                },
                "onset_tol_ms": {"type": "integer", "minimum": 10, "maximum": 500, "default": 75},
                "task_id": {"type": "string"},
            },
            "required": ["arrangement_id"],
        },
    },
    {
        "name": "preview",
        "description": "Synthesize a local offline WAV preview for an arrangement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "arrangement_id": {"type": "string"},
                "output_path": {"type": "string"},
                "sample_rate": {
                    "type": "integer",
                    "minimum": 8000,
                    "maximum": 48000,
                    "default": 22050,
                },
                "fixed_velocity": {"type": "boolean", "default": False},
                "timbre": {
                    "type": "string",
                    "enum": ["auto", "piano", "lyre", "zither", "vintage"],
                    "default": "auto",
                },
                "task_id": {"type": "string"},
            },
            "required": ["arrangement_id"],
        },
    },
    {
        "name": "save_to_library",
        "description": (
            "Atomically update song metadata (title, artist, tags) or arrangement label/vote "
            "(short DB transaction: cancellation takes effect before commit; committed updates "
            "are not rolled back)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "string"},
                "title": {"type": "string"},
                "artist": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "arrangement_id": {"type": "string"},
                "label": {"type": "string"},
                "is_favorite": {"type": "boolean"},
                "user_vote": {"type": "integer", "enum": [-1, 0, 1]},
                "task_id": {"type": "string"},
            },
        },
    },
    {
        "name": "export_score",
        "description": (
            "Export an arrangement to MIDI, performance JSON, or a .lyrapack share package "
            "(requires rights_confirmed=true for .lyrapack; never includes raw audio or secrets; "
            "cancellation aborts before file write)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "arrangement_id": {"type": "string"},
                "format": {"type": "string", "enum": ["midi", "json", "lyrapack"]},
                "output_path": {"type": "string"},
                "rights_confirmed": {"type": "boolean", "default": False},
                "task_id": {"type": "string"},
            },
            "required": ["arrangement_id", "format", "output_path"],
        },
    },
    {
        "name": "get_task_status",
        "description": "Inspect recent MCP task status/logs or cancel an active task by task_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "cancel": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "play_in_game",
        "description": (
            "Sensitive gate: returns explicit user confirmation requirements for OS keyboard "
            "playback; never triggers game input automatically from MCP."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "arrangement_id": {"type": "string"},
                "profile_id": {"type": "string"},
            },
            "required": ["arrangement_id"],
        },
    },
]


def _bound_int(
    args: dict[str, Any],
    key: str,
    *,
    lo: int,
    hi: int,
    default: int | None = None,
) -> int:
    raw = args.get(key, default)
    if raw is None or isinstance(raw, bool):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT, f"{key} must be an integer between {lo} and {hi}"
        )
    if isinstance(raw, float) and not raw.is_integer():
        raise LyraError(ErrorCode.INVALID_ARGUMENT, f"{key} must be an integer")
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT, f"{key} must be an integer between {lo} and {hi}"
        ) from exc
    if not (lo <= val <= hi):
        raise LyraError(ErrorCode.INVALID_ARGUMENT, f"{key} must be within [{lo}, {hi}]")
    return val


_TRACKED_TOOLS = frozenset({
    "search_music",
    "import_media",
    "transcribe",
    "arrange",
    "evaluate",
    "preview",
    "save_to_library",
    "export_score",
})


def _call_with_cancel(
    fn: Callable[..., Any],
    *args: Any,
    is_cancelled: Callable[[], bool],
    cancel_message: str,
    **kwargs: Any,
) -> Any:
    if is_cancelled():
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, cancel_message)
    supports_cancel = False
    try:
        sig = inspect.signature(fn)
        params = sig.parameters.values()
        supports_cancel = "is_cancelled" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params
        )
    except (TypeError, ValueError):
        supports_cancel = False
    if supports_cancel:
        return fn(*args, is_cancelled=is_cancelled, **kwargs)
    result = fn(*args, **kwargs)
    if is_cancelled():
        raise LyraError(ErrorCode.PLAYBACK_ABORTED, cancel_message)
    return result


class MCPToolExecutor:
    """Executes typed MCP tool calls cleanly against LibraryStore and SourceAdapters."""

    def __init__(
        self,
        store: LibraryStore,
        *,
        search_dirs: Sequence[str | Path] = (),
        default_allow_network: bool = False,
        url_adapter: DirectUrlSourceAdapter | None = None,
        online_adapter: OpenMusicCatalogSourceAdapter | None = None,
        tasks: MCPTaskRegistry | None = None,
    ) -> None:
        self.store = store
        self._owner_thread_id = threading.get_ident()
        self._search_dirs = tuple(search_dirs)
        self.default_allow_network = default_allow_network
        self.local_adapter = LocalLibrarySourceAdapter(store=store, search_dirs=search_dirs)
        self.url_adapter = url_adapter or DirectUrlSourceAdapter()
        self.online_adapter = online_adapter or OpenMusicCatalogSourceAdapter()
        self.tasks = tasks or MCPTaskRegistry()
        self._default_handlers: dict[
            str,
            Callable[
                [dict[str, Any], str | int | None, LibraryStore, StopToken | None],
                dict[str, Any],
            ],
        ] = {
            "search_music": self._tool_search_music,
            "import_media": self._tool_import_media,
            "transcribe": self._tool_transcribe,
            "arrange": self._tool_arrange,
            "evaluate": self._tool_evaluate,
            "preview": self._tool_preview,
            "save_to_library": self._tool_save_to_library,
            "export_score": self._tool_export_score,
            "get_task_status": self._tool_get_task_status,
            "play_in_game": self._tool_play_in_game,
        }
        self._handlers = dict(self._default_handlers)

    @contextmanager
    def _thread_store(self) -> Iterator[LibraryStore]:
        if threading.get_ident() == self._owner_thread_id:
            yield self.store
            return
        with LibraryStore(self.store.data_dir, secret_store=self.store._secrets) as worker_store:
            yield worker_store

    def list_tools(self) -> list[dict[str, Any]]:
        return list(TOOL_SCHEMAS)

    def _run_tracked(
        self,
        tool_name: str,
        args: dict[str, Any],
        req_id: str | int | None,
        stop_token: StopToken | None,
        fn: Callable[[MCPTaskRecord], dict[str, Any]],
        *,
        complete_message: str | None = None,
    ) -> dict[str, Any]:
        raw_tid = args.get("task_id")
        req_tid = str(raw_tid).strip() if isinstance(raw_tid, str) and raw_tid.strip() else None
        if stop_token is not None and stop_token.stopped:
            if req_tid:
                self.tasks.consume_pre_cancel(req_tid)
            if req_id is not None:
                self.tasks.consume_pre_cancel(str(req_id))
        pre_req = (
            self.tasks.is_pre_cancelled(str(req_id)) if req_id is not None else False
        )
        pre_tid = self.tasks.is_pre_cancelled(req_tid) if req_tid is not None else False
        if (stop_token is not None and stop_token.stopped) or pre_req or pre_tid:
            reason = (
                stop_token.reason
                if stop_token is not None and stop_token.stopped and stop_token.reason
                else None
            )
            if req_id is not None:
                reason = self.tasks.consume_pre_cancel(str(req_id)) or reason
            if req_tid is not None:
                reason = self.tasks.consume_pre_cancel(req_tid) or reason
            # Best-effort record if capacity permits, without hitting LIMIT_EXCEEDED on cancel
            if self.tasks.active_count() < self.tasks._max_tasks:
                tok_c = stop_token or StopToken()
                tok_c.request_stop(reason or f"{tool_name} cancelled prior to execution")
                self.tasks.create(
                    tool_name, task_id=req_tid, request_id=req_id, stop_token=tok_c
                )
            raise LyraError(
                ErrorCode.PLAYBACK_ABORTED,
                reason or f"{tool_name} cancelled prior to execution",
            )

        task = self.tasks.create(
            tool_name,
            task_id=req_tid,
            request_id=req_id,
            stop_token=stop_token,
        )
        try:
            payload = fn(task)
        except LyraError as exc:
            status = "cancelled" if exc.code == ErrorCode.PLAYBACK_ABORTED else "failed"
            self.tasks.finish(
                task.task_id,
                status=status,
                error={"code": exc.code.value, "message": exc.message},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self.tasks.finish(
                task.task_id,
                status="failed",
                error={"code": ErrorCode.INVALID_ARGUMENT.value, "message": str(exc)},
            )
            raise
        self.tasks.finish(
            task.task_id,
            status="completed",
            progress=1.0,
            message=complete_message or f"{tool_name} completed",
        )
        out = dict(payload)
        out.setdefault("task_id", task.task_id)
        return out

    def call(
        self,
        name: str,
        arguments: Any = None,
        *,
        request_id: str | int | None = None,
        stop_token: StopToken | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Return ``(payload, is_error)`` for an MCP ``tools/call`` invocation."""
        if arguments is not None and not isinstance(arguments, dict):
            return (
                {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.INVALID_ARGUMENT.value,
                        "message": "tools/call 'arguments' must be a JSON object",
                        "recoverable": True,
                    },
                },
                True,
            )
        args: dict[str, Any] = dict(arguments) if isinstance(arguments, dict) else {}
        handler = self._handlers.get(name)
        if handler is None:
            return (
                {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.INVALID_ARGUMENT.value,
                        "message": f"unknown MCP tool {name!r}",
                        "recoverable": False,
                    },
                },
                True,
            )
        try:
            uses_default_tracked = (
                name in _TRACKED_TOOLS and handler == self._default_handlers.get(name)
            )
            if not uses_default_tracked and name != "get_task_status":
                pre_reason = (
                    self.tasks.consume_pre_cancel(str(request_id))
                    if request_id is not None
                    else None
                )
                if (stop_token is not None and stop_token.stopped) or pre_reason is not None:
                    raise LyraError(
                        ErrorCode.PLAYBACK_ABORTED,
                        (
                            stop_token.reason
                            if stop_token is not None and stop_token.stopped and stop_token.reason
                            else pre_reason or "request cancelled"
                        ),
                    )
            with self._thread_store() as store:
                payload = handler(args, request_id, store, stop_token)
            return payload, False
        except LyraError as exc:
            secret_val = ""
            with suppress(Exception):
                secret_val = self.store._secrets.get("llm_api_key") or ""
            return (
                {
                    "ok": False,
                    "error": {
                        "code": exc.code.value,
                        "message": redact_secret(exc.message, (secret_val,)),
                        "details": exc.details,
                        "recoverable": exc.code
                        in {
                            ErrorCode.PERMISSION_REQUIRED,
                            ErrorCode.SOURCE_UNAVAILABLE,
                            ErrorCode.INVALID_ARGUMENT,
                            ErrorCode.PLAYBACK_ABORTED,
                            ErrorCode.LIMIT_EXCEEDED,
                            ErrorCode.LIBRARY_BUSY,
                        },
                    },
                },
                True,
            )
        except Exception as exc:  # noqa: BLE001
            secret_val = ""
            with suppress(Exception):
                secret_val = self.store._secrets.get("llm_api_key") or ""
            return (
                {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.INVALID_ARGUMENT.value,
                        "message": redact_secret(str(exc), (secret_val,)),
                        "recoverable": False,
                    },
                },
                True,
            )

    def _tool_search_music(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "query must not be empty")
        limit = _bound_int(args, "limit", default=10, lo=1, hi=50)
        allow_net = bool(args.get("allow_network", self.default_allow_network))

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            is_cancelled = lambda: task.stop_token.stopped  # noqa: E731
            local_adapter = (
                self.local_adapter
                if store is self.store
                else LocalLibrarySourceAdapter(store=store, search_dirs=self._search_dirs)
            )
            self.tasks.log(task.task_id, 0.2, "searching local sources")
            local = _call_with_cancel(
                local_adapter.search,
                query,
                limit=limit,
                is_cancelled=is_cancelled,
                cancel_message="search_music cancelled",
            )
            remote = []
            if allow_net:
                self.tasks.log(task.task_id, 0.5, "searching open music catalog")
                remote = _call_with_cancel(
                    self.online_adapter.search,
                    query,
                    limit=limit,
                    is_cancelled=is_cancelled,
                    cancel_message="search_music cancelled",
                )
            if task.stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "search_music cancelled")
            ranked = rank_candidates([*local, *remote], query)[:limit]
            return {
                "ok": True,
                "query": query,
                "allow_network": allow_net,
                "candidates": [c.to_json() for c in ranked],
                "network_note": (
                    None
                    if allow_net
                    else "Online catalog search skipped (allow_network=false)."
                ),
            }

        return self._run_tracked("search_music", args, req_id, stop_token, _work)

    def _tool_import_media(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        path_raw = args.get("path")
        url_raw = args.get("url")
        title = str(args["title"]).strip() if args.get("title") else None
        artist = str(args.get("artist") or "").strip()
        tags = [str(t) for t in args["tags"]] if isinstance(args.get("tags"), list) else None
        if not path_raw and not url_raw:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "provide either 'path' or 'url'")

        if url_raw:
            allow_net = bool(args.get("allow_network", self.default_allow_network))
            if not allow_net:
                raise LyraError(
                    ErrorCode.PERMISSION_REQUIRED,
                    "explicit allow_network=true required to download remote media URL",
                )

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            is_cancelled = lambda: task.stop_token.stopped  # noqa: E731
            if url_raw:
                self.tasks.log(task.task_id, 0.2, "downloading media from URL")
                with tempfile.TemporaryDirectory(prefix="lyraforge-mcp-dl-") as tmpdir:
                    local_file = _call_with_cancel(
                        self.url_adapter.fetch,
                        str(url_raw).strip(),
                        Path(tmpdir),
                        user_authorized=True,
                        is_cancelled=is_cancelled,
                        cancel_message="import_media cancelled",
                    )
                    self.tasks.log(task.task_id, 0.7, "importing downloaded media")
                    return self._import_local_path(
                        store,
                        local_file,
                        title=title,
                        artist=artist,
                        tags=tags,
                        stop_token=task.stop_token,
                    )
            self.tasks.log(task.task_id, 0.3, "importing local media")
            return self._import_local_path(
                store,
                Path(str(path_raw)).expanduser(),
                title=title,
                artist=artist,
                tags=tags,
                stop_token=task.stop_token,
            )

        return self._run_tracked("import_media", args, req_id, stop_token, _work)

    def _import_local_path(
        self,
        store: LibraryStore,
        path: Path,
        *,
        title: str | None,
        artist: str,
        tags: list[str] | None,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        ext = path.suffix.lower()
        if ext in {".mid", ".midi"}:
            res = store.import_midi(
                path, title=title, artist=artist, tags=tags, stop_token=stop_token
            )
        else:
            res = store.import_audio(
                path, title=title, artist=artist, tags=tags, stop_token=stop_token
            )
        return {
            "ok": True,
            "song": res.song.to_json(),
            "source": res.source.to_json(),
            "deduplicated": res.deduplicated,
        }

    def _tool_transcribe(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        song_id = str(args.get("song_id") or "").strip()
        if not song_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "song_id is required")
        pipeline_id = str(args.get("pipeline_id") or "direct")
        engine_id = str(args.get("engine_id") or DEFAULT_TRANSCRIBER_ID)
        vocal_engine_id = (
            str(args["vocal_engine_id"]).strip() if args.get("vocal_engine_id") else None
        )
        accomp_engine_id = (
            str(args["accomp_engine_id"]).strip() if args.get("accomp_engine_id") else None
        )
        vocal_cleanup = str(args.get("vocal_cleanup") or "standard")
        vocal_range = str(args.get("vocal_range") or "auto")
        opts = TranscribeOptions(
            min_pitch=_bound_int(args, "min_pitch", default=36, lo=0, hi=126),
            max_pitch=_bound_int(args, "max_pitch", default=96, lo=1, hi=127),
            min_note_ms=_bound_int(args, "min_note_ms", default=60, lo=10, hi=5000),
        )

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            rec = store.transcribe_song(
                song_id,
                engine_id=engine_id,
                pipeline_id=pipeline_id,
                vocal_engine_id=vocal_engine_id,
                accomp_engine_id=accomp_engine_id,
                vocal_cleanup=vocal_cleanup,
                vocal_range=vocal_range,
                options=opts,
                on_progress=lambda p, msg: self.tasks.log(task.task_id, p, msg),
                stop_token=task.stop_token,
            )
            return {
                "ok": True,
                "task_id": task.task_id,
                "transcription": rec.to_json(),
                "status": "completed",
            }

        return self._run_tracked("transcribe", args, req_id, stop_token, _work)

    def _tool_arrange(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        song_id = str(args.get("song_id") or "").strip()
        if not song_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "song_id is required")
        raw_inc = args.get("include_tracks")
        include_tracks = (
            tuple(int(t) for t in raw_inc) if isinstance(raw_inc, list) else None
        )
        opts = ArrangeOptions(
            style=Style(str(args.get("style") or Style.BALANCED.value)),
            transpose=int(args["transpose"]) if args.get("transpose") is not None else None,
            semitone_policy=SemitonePolicy(
                str(args.get("semitone_policy") or SemitonePolicy.NEAREST.value)
            ),
            speed=float(args.get("speed", 1.0)),
            max_chord_keys=(
                _bound_int(args, "max_chord_keys", lo=1, hi=32)
                if args.get("max_chord_keys") is not None
                else None
            ),
            chord_window_ms=_bound_int(args, "chord_window_ms", default=20, lo=0, hi=200),
            arpeggiate_ms=_bound_int(args, "arpeggiate_ms", default=0, lo=0, hi=60),
            include_tracks=include_tracks,
            arranger_strategy=str(args.get("arranger_strategy") or "classic"),
            melody_track=(
                int(args["melody_track"]) if args.get("melody_track") is not None else None
            ),
            vocal_ducking=bool(args.get("vocal_ducking", True)),
            melody_ceiling=bool(args.get("melody_ceiling", True)),
            anti_clash_semitones=bool(args.get("anti_clash_semitones", True)),
            timing_mode=str(args.get("timing_mode") or "adapted"),
            accomp_density=(
                str(args["accomp_density"]).strip() if args.get("accomp_density") else None
            ),
            phrase_octave_mode=(
                str(args["phrase_octave_mode"]).strip()
                if args.get("phrase_octave_mode")
                else None
            ),
            cross_stem_align_ms=(
                _bound_int(args, "cross_stem_align_ms", lo=0, hi=60)
                if args.get("cross_stem_align_ms") is not None
                else None
            ),
        )
        transcription_id = (
            str(args["transcription_id"]).strip() if args.get("transcription_id") else None
        )

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            self.tasks.log(task.task_id, 0.2, "arranging score")
            rec = store.arrange_song(
                song_id,
                profile_id=str(args.get("profile_id") or DEFAULT_PROFILE_ID),
                options=opts,
                label=str(args["label"]) if args.get("label") else None,
                transcription_id=transcription_id,
                stop_token=task.stop_token,
            )
            report = store.load_arrangement_report(rec.id)
            return {
                "ok": True,
                "arrangement": rec.to_json(),
                "arrangement_playability_vs_input_midi": {
                    "quality": report.get("quality"),
                    "stats": report.get("stats"),
                    "calibration_status": report.get("calibration_status"),
                },
            }

        return self._run_tracked("arrange", args, req_id, stop_token, _work)

    def _tool_evaluate(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        if not arr_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "arrangement_id is required")

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            if task.stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "evaluate cancelled")
            rec = store.get_arrangement(arr_id)
            report = store.load_arrangement_report(arr_id)
            out: dict[str, Any] = {
                "ok": True,
                "arrangement": rec.to_json(),
                "arrangement_playability_vs_input_midi": {
                    "quality": report.get("quality"),
                    "stats": report.get("stats"),
                    "calibration_status": report.get("calibration_status"),
                },
                "subjective_preview_quality": "unrated_manual_preview_required",
            }
            other_id = args.get("compare_with_arrangement_id")
            if other_id:
                if task.stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "evaluate cancelled")
                out["ab_comparison"] = store.compare_arrangements(arr_id, str(other_id).strip())
            ref_raw = args.get("reference_midi_path")
            if ref_raw:
                if task.stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "evaluate cancelled")
                tol = _bound_int(args, "onset_tol_ms", default=75, lo=10, hi=500)
                ref_score = load_midi_file(Path(str(ref_raw)).expanduser())
                ref_pairs = [
                    (round(n.start_us / 1000.0), n.pitch)
                    for n in ref_score.notes
                    if not n.is_percussion
                ]
                detail = store.get_song(rec.song_id)
                matched_tr = None
                if rec.transcription_id:
                    matched_tr = next(
                        (t for t in detail.transcriptions if t.id == rec.transcription_id),
                        None,
                    )
                if matched_tr is None and detail.transcriptions:
                    matched_tr = detail.transcriptions[0]
                if matched_tr is not None:
                    if task.stop_token.stopped:
                        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "evaluate cancelled")
                    tr_mid = load_midi_file(
                        resolve_under(store.data_dir, matched_tr.cleaned_midi_path)
                    )
                    out["transcription_fidelity"] = evaluate_transcription_against_reference(
                        ref_pairs, tr_mid.notes, onset_tol_ms=tol, pitch_tol_semitones=1
                    ).to_json()
                if task.stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "evaluate cancelled")
                perf = store.load_arrangement_performance(arr_id)
                ev_rows = perf.get("events") or []
                out["end_to_end_vs_reference"] = evaluate_events_against_reference(
                    ref_pairs,
                    [(int(ev["at_ms"]), int(ev["mapped_pitch"])) for ev in ev_rows],
                    transpose=rec.transpose,
                    onset_tol_ms=tol,
                )
            return out

        return self._run_tracked("evaluate", args, req_id, stop_token, _work)

    def _tool_preview(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        if not arr_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "arrangement_id is required")
        sr = _bound_int(args, "sample_rate", default=22050, lo=8000, hi=48000)
        fixed_vel = bool(args.get("fixed_velocity", False))
        timbre = str(args.get("timbre") or "auto").strip().lower()

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            self.tasks.log(task.task_id, 0.2, "rendering preview WAV")
            wav_path = store.render_preview(
                arr_id,
                sample_rate=sr,
                fixed_velocity=fixed_vel,
                timbre=timbre,
                stop_token=task.stop_token,
            )
            out_raw = args.get("output_path")
            if out_raw:
                if task.stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "preview cancelled before save")
                dest = Path(str(out_raw)).expanduser().resolve()
                dest.parent.mkdir(parents=True, exist_ok=True)
                wav_bytes = wav_path.read_bytes()
                if task.stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "preview cancelled before save")
                atomic_write_bytes(dest, wav_bytes)
                wav_path = dest
            rec = store.get_arrangement(arr_id)
            return {
                "ok": True,
                "arrangement_id": arr_id,
                "wav_path": str(wav_path),
                "size_bytes": wav_path.stat().st_size,
                "duration_ms": rec.duration_ms,
                "fixed_velocity": fixed_vel,
                "timbre": timbre,
            }

        return self._run_tracked("preview", args, req_id, stop_token, _work)

    def _tool_save_to_library(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        song_id = args.get("song_id")
        arr_id = args.get("arrangement_id")
        vote_val: int | None = None
        if arr_id and args.get("user_vote") is not None:
            vote_val = _bound_int(args, "user_vote", lo=-1, hi=1)

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            tags = [str(t) for t in args["tags"]] if isinstance(args.get("tags"), list) else None
            updates = store.save_library_updates(
                song_id=str(song_id).strip() if song_id else None,
                title=str(args["title"]) if song_id and args.get("title") is not None else None,
                artist=str(args["artist"]) if song_id and args.get("artist") is not None else None,
                tags=tags if song_id else None,
                arrangement_id=str(arr_id).strip() if arr_id else None,
                label=str(args["label"]) if arr_id and args.get("label") is not None else None,
                is_favorite=(
                    bool(args["is_favorite"])
                    if arr_id and args.get("is_favorite") is not None
                    else None
                ),
                user_vote=vote_val,
                stop_token=task.stop_token,
            )
            return {"ok": True, **updates}

        return self._run_tracked("save_to_library", args, req_id, stop_token, _work)

    def _tool_export_score(
        self,
        args: dict[str, Any],
        req_id: str | int | None,
        store: LibraryStore,
        stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        fmt = str(args.get("format") or "").strip().lower()
        out_raw = str(args.get("output_path") or "").strip()
        if not arr_id or not fmt or not out_raw:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "arrangement_id, format, and output_path are required"
            )
        if fmt not in {"lyrapack", "midi", "json"}:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, f"unsupported export format {fmt!r}")

        def _work(task: MCPTaskRecord) -> dict[str, Any]:
            dest = Path(out_raw).expanduser().resolve()
            if task.stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "export_score cancelled")
            if fmt == "lyrapack":
                payload = export_lyrapack(
                    store,
                    arr_id,
                    copyright_confirmed=bool(args.get("rights_confirmed", False)),
                    is_cancelled=lambda: task.stop_token.stopped,
                )
            else:
                payload = store.export_arrangement(arr_id, fmt)  # type: ignore[arg-type]
            if task.stop_token.stopped:
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, "export_score cancelled before save")
            atomic_write_bytes(dest, payload)
            return {
                "ok": True,
                "format": fmt,
                "output_path": str(dest),
                "size_bytes": len(payload),
                "includes_source_audio": False,
            }

        return self._run_tracked("export_score", args, req_id, stop_token, _work)

    def _tool_get_task_status(
        self,
        args: dict[str, Any],
        _req_id: str | int | None,
        _store: LibraryStore,
        _stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        task_id = args.get("task_id")
        if task_id:
            tid = str(task_id).strip()
            if bool(args.get("cancel", False)):
                rec = self.tasks.cancel(tid)
                if rec is None:
                    raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"unknown task_id {tid!r}")
                return {"ok": True, "task": rec.to_json()}
            rec = self.tasks.get(tid)
            if rec is None:
                raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"unknown task_id {tid!r}")
            return {"ok": True, "task": rec.to_json()}
        return {"ok": True, "tasks": self.tasks.list_recent()}

    def _tool_play_in_game(
        self,
        args: dict[str, Any],
        _req_id: str | int | None,
        store: LibraryStore,
        _stop_token: StopToken | None = None,
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        if not arr_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "arrangement_id is required")
        rec = store.get_arrangement(arr_id)
        prof_id = str(args.get("profile_id") or rec.profile_id or DEFAULT_PROFILE_ID)
        profile = load_builtin_profile(prof_id)
        return {
            "ok": False,
            "executed": False,
            "status": "blocked_requires_interactive_confirmation",
            "requires_user_confirmation": True,
            "arrangement_id": rec.id,
            "profile_id": profile.id,
            "calibration_status": profile.calibration_status,
            "message": (
                "OS keyboard playback is disabled for unattended MCP/agent calls. "
                "Open the LyraForge desktop workbench, focus Genshin Impact's free-play "
                "instrument interface on Windows, and complete the two-step explicit "
                "authorization in the UI."
            ),
        }
