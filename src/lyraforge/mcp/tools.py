"""Typed MCP tool definitions, task/cancellation registry, and LyraForge dispatchers."""

from __future__ import annotations

import shutil
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

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool": self.tool,
            "status": self.status,
            "progress": round(self.progress, 4),
            "logs": list(self.logs[-50:]),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MCPTaskRegistry:
    """Thread-safe task status, progress log, and cancellation token store."""

    def __init__(self, max_tasks: int = 100) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, MCPTaskRecord] = {}
        self._request_to_task: dict[str, str] = {}
        self._pre_cancelled: dict[str, str] = {}
        self._max_tasks = max(1, int(max_tasks))

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
            token = stop_token or StopToken()
            rec = MCPTaskRecord(
                task_id=tid,
                tool=tool,
                status="running",
                progress=0.0,
                stop_token=token,
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
                rec.logs.append("cancelled prior to execution")
            elif rec.stop_token.stopped:
                rec.status = "cancelled"
                rec.logs.append("cancelled prior to execution")

            self._tasks[tid] = rec
            self._evict_excess_locked(keep_id=tid)
            return rec

    def _evict_excess_locked(self, *, keep_id: str) -> None:
        while len(self._tasks) > self._max_tasks:
            evict_id = next(
                (
                    k
                    for k, v in self._tasks.items()
                    if k != keep_id and v.status not in {"queued", "running"}
                ),
                None,
            )
            if evict_id is None:
                evict_id = next((k for k in self._tasks if k != keep_id), None)
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
            if progress is not None:
                rec.progress = max(0.0, min(1.0, float(progress)))
            if message:
                rec.logs.append(message)
            rec.error = error
            rec.updated_at = datetime.now(UTC).isoformat()

    def cancel(self, target_id: str) -> MCPTaskRecord | None:
        with self._lock:
            key = str(target_id)
            tid = self._request_to_task.get(key, key)
            rec = self._tasks.get(tid)
            if rec is None:
                self._pre_cancelled[key] = f"cancelled via MCP ({key})"
                max_pre = self._max_tasks * 4
                while len(self._pre_cancelled) > max_pre:
                    oldest_pre = next(iter(self._pre_cancelled))
                    del self._pre_cancelled[oldest_pre]
                return None
            if rec.status in {"queued", "running"}:
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
                if rec.status in {"queued", "running"}:
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
            },
            "required": ["query"],
        },
    },
    {
        "name": "import_media",
        "description": (
            "Import a local MIDI/audio/video file or user-authorized public HTTP(S) URL "
            "into the LyraForge library."
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
            },
        },
    },
    {
        "name": "transcribe",
        "description": (
            "Transcribe an imported audio/video song in the library to MIDI using builtin-mono "
            "(YIN) or a configured isolated external engine."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "string"},
                "engine_id": {"type": "string", "default": DEFAULT_TRANSCRIBER_ID},
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
            "Arrange a song (from MIDI source or latest transcription) for a Genshin Impact "
            "instrument profile and persist the arrangement version."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "string"},
                "profile_id": {"type": "string", "default": DEFAULT_PROFILE_ID},
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
                "label": {"type": "string"},
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
            },
            "required": ["arrangement_id"],
        },
    },
    {
        "name": "save_to_library",
        "description": "Update song metadata (title, artist, tags) or arrangement label/vote.",
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
            },
        },
    },
    {
        "name": "export_score",
        "description": (
            "Export an arrangement to MIDI, performance JSON, or a .lyrapack share package "
            "(requires rights_confirmed=true for .lyrapack; never includes raw audio or secrets)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "arrangement_id": {"type": "string"},
                "format": {"type": "string", "enum": ["midi", "json", "lyrapack"]},
                "output_path": {"type": "string"},
                "rights_confirmed": {"type": "boolean", "default": False},
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
        self._handlers: dict[
            str,
            Callable[
                [dict[str, Any], str | int | None, LibraryStore, StopToken | None],
                dict[str, Any],
            ],
        ] = {
            "search_music": lambda a, r, s, _st: self._tool_search_music(a, r, s),
            "import_media": lambda a, r, s, _st: self._tool_import_media(a, r, s),
            "transcribe": self._tool_transcribe,
            "arrange": lambda a, r, s, _st: self._tool_arrange(a, r, s),
            "evaluate": lambda a, r, s, _st: self._tool_evaluate(a, r, s),
            "preview": lambda a, r, s, _st: self._tool_preview(a, r, s),
            "save_to_library": lambda a, r, s, _st: self._tool_save_to_library(a, r, s),
            "export_score": lambda a, r, s, _st: self._tool_export_score(a, r, s),
            "get_task_status": lambda a, r, s, _st: self._tool_get_task_status(a, r, s),
            "play_in_game": lambda a, r, s, _st: self._tool_play_in_game(a, r, s),
        }

    @contextmanager
    def _thread_store(self) -> Iterator[LibraryStore]:
        if threading.get_ident() == self._owner_thread_id:
            yield self.store
            return
        with LibraryStore(self.store.data_dir, secret_store=self.store._secrets) as worker_store:
            yield worker_store

    def list_tools(self) -> list[dict[str, Any]]:
        return list(TOOL_SCHEMAS)

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
            if name != "transcribe":
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
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "query must not be empty")
        limit = _bound_int(args, "limit", default=10, lo=1, hi=50)
        allow_net = bool(args.get("allow_network", self.default_allow_network))
        local_adapter = (
            self.local_adapter
            if store is self.store
            else LocalLibrarySourceAdapter(store=store, search_dirs=self._search_dirs)
        )
        local = local_adapter.search(query, limit=limit)
        remote = self.online_adapter.search(query, limit=limit) if allow_net else []
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

    def _tool_import_media(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
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
            with tempfile.TemporaryDirectory(prefix="lyraforge-mcp-dl-") as tmpdir:
                local_file = self.url_adapter.fetch(
                    str(url_raw).strip(), Path(tmpdir), user_authorized=True
                )
                return self._import_local_path(
                    store, local_file, title=title, artist=artist, tags=tags
                )
        return self._import_local_path(
            store, Path(str(path_raw)).expanduser(), title=title, artist=artist, tags=tags
        )

    def _import_local_path(
        self,
        store: LibraryStore,
        path: Path,
        *,
        title: str | None,
        artist: str,
        tags: list[str] | None,
    ) -> dict[str, Any]:
        ext = path.suffix.lower()
        if ext in {".mid", ".midi"}:
            res = store.import_midi(path, title=title, artist=artist, tags=tags)
        else:
            res = store.import_audio(path, title=title, artist=artist, tags=tags)
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
        engine_id = str(args.get("engine_id") or DEFAULT_TRANSCRIBER_ID)
        opts = TranscribeOptions(
            min_pitch=_bound_int(args, "min_pitch", default=36, lo=0, hi=126),
            max_pitch=_bound_int(args, "max_pitch", default=96, lo=1, hi=127),
            min_note_ms=_bound_int(args, "min_note_ms", default=60, lo=10, hi=5000),
        )
        task = self.tasks.create(
            "transcribe",
            task_id=str(args.get("task_id") or "") or None,
            request_id=req_id,
            stop_token=stop_token,
        )
        try:
            rec = store.transcribe_song(
                song_id,
                engine_id=engine_id,
                options=opts,
                on_progress=lambda p, msg: self.tasks.log(task.task_id, p, msg),
                stop_token=task.stop_token,
            )
        except LyraError as exc:
            status = "cancelled" if exc.code == ErrorCode.PLAYBACK_ABORTED else "failed"
            self.tasks.finish(
                task.task_id,
                status=status,
                error={"code": exc.code.value, "message": exc.message},
            )
            raise
        self.tasks.finish(
            task.task_id,
            status="completed",
            progress=1.0,
            message=f"transcribed {rec.note_count} notes via {rec.engine}",
        )
        return {
            "ok": True,
            "task_id": task.task_id,
            "transcription": rec.to_json(),
            "status": "completed",
        }

    def _tool_arrange(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        song_id = str(args.get("song_id") or "").strip()
        if not song_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "song_id is required")
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
        )
        rec = store.arrange_song(
            song_id,
            profile_id=str(args.get("profile_id") or DEFAULT_PROFILE_ID),
            options=opts,
            label=str(args["label"]) if args.get("label") else None,
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

    def _tool_evaluate(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        if not arr_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "arrangement_id is required")
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
            out["ab_comparison"] = store.compare_arrangements(arr_id, str(other_id).strip())
        ref_raw = args.get("reference_midi_path")
        if ref_raw:
            tol = _bound_int(args, "onset_tol_ms", default=75, lo=10, hi=500)
            ref_score = load_midi_file(Path(str(ref_raw)).expanduser())
            ref_pairs = [
                (round(n.start_us / 1000.0), n.pitch)
                for n in ref_score.notes
                if not n.is_percussion
            ]
            # If the song has a transcription MIDI, compute fidelity vs reference as well
            detail = store.get_song(rec.song_id)
            if detail.transcriptions:
                tr_mid = load_midi_file(
                    resolve_under(store.data_dir, detail.transcriptions[0].cleaned_midi_path)
                )
                out["transcription_fidelity"] = evaluate_transcription_against_reference(
                    ref_pairs, tr_mid.notes, onset_tol_ms=tol, pitch_tol_semitones=1
                ).to_json()
            # Compare persisted arrangement events directly against reference
            perf = store.load_arrangement_performance(arr_id)
            ev_rows = perf.get("events") or []
            out["end_to_end_vs_reference"] = evaluate_events_against_reference(
                ref_pairs,
                [(int(ev["at_ms"]), int(ev["mapped_pitch"])) for ev in ev_rows],
                transpose=rec.transpose,
                onset_tol_ms=tol,
            )
        return out

    def _tool_preview(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        if not arr_id:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "arrangement_id is required")
        sr = _bound_int(args, "sample_rate", default=22050, lo=8000, hi=48000)
        wav_path = store.render_preview(arr_id, sample_rate=sr)
        out_raw = args.get("output_path")
        if out_raw:
            dest = Path(str(out_raw)).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wav_path, dest)
            wav_path = dest
        rec = store.get_arrangement(arr_id)
        return {
            "ok": True,
            "arrangement_id": arr_id,
            "wav_path": str(wav_path),
            "size_bytes": wav_path.stat().st_size,
            "duration_ms": rec.duration_ms,
        }

    def _tool_save_to_library(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True}
        song_id = args.get("song_id")
        if song_id:
            tags = [str(t) for t in args["tags"]] if isinstance(args.get("tags"), list) else None
            updated_song = store.update_song_metadata(
                str(song_id).strip(),
                title=str(args["title"]) if args.get("title") is not None else None,
                artist=str(args["artist"]) if args.get("artist") is not None else None,
                tags=tags,
            )
            out["song"] = updated_song.to_json()
        arr_id = args.get("arrangement_id")
        if arr_id:
            aid = str(arr_id).strip()
            rec = store.get_arrangement(aid)
            if args.get("label") is not None:
                rec = store.set_arrangement_label(aid, str(args["label"]))
            if args.get("is_favorite") is not None:
                rec = store.set_favorite(aid, bool(args["is_favorite"]))
            if args.get("user_vote") is not None:
                vote_val = _bound_int(args, "user_vote", lo=-1, hi=1)
                rec = store.set_user_vote(aid, vote_val)
            out["arrangement"] = rec.to_json()
        if "song" not in out and "arrangement" not in out:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "provide 'song_id' and/or 'arrangement_id'"
            )
        return out

    def _tool_export_score(
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
    ) -> dict[str, Any]:
        arr_id = str(args.get("arrangement_id") or "").strip()
        fmt = str(args.get("format") or "").strip().lower()
        out_raw = str(args.get("output_path") or "").strip()
        if not arr_id or not fmt or not out_raw:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, "arrangement_id, format, and output_path are required"
            )
        dest = Path(out_raw).expanduser().resolve()
        if fmt == "lyrapack":
            payload = export_lyrapack(
                store,
                arr_id,
                copyright_confirmed=bool(args.get("rights_confirmed", False)),
            )
        elif fmt in {"midi", "json"}:
            payload = store.export_arrangement(arr_id, fmt)  # type: ignore[arg-type]
        else:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT, f"unsupported export format {fmt!r}"
            )
        atomic_write_bytes(dest, payload)
        return {
            "ok": True,
            "format": fmt,
            "output_path": str(dest),
            "size_bytes": len(payload),
            "includes_source_audio": False,
        }

    def _tool_get_task_status(
        self, args: dict[str, Any], _req_id: str | int | None, _store: LibraryStore
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
        self, args: dict[str, Any], _req_id: str | int | None, store: LibraryStore
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
