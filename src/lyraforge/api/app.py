"""Local FastAPI service (127.0.0.1 + per-session token auth)."""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
from typing import Any

import anyio
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lyraforge import __version__
from lyraforge.agent import ALLOWED_TOOLS, FORBIDDEN_TOOLS, AgentOrchestrator
from lyraforge.api.job_service import TranscriptionJobManager
from lyraforge.api.playback_service import PlaybackManager
from lyraforge.api.queue_service import PlaybackQueueManager, QueueItem
from lyraforge.api.tool_service import ToolInstallManager
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.hotkeys import ACTION_LABELS, HOTKEY_ACTIONS, HotkeyRegistry
from lyraforge.instruments import DEFAULT_PROFILE_ID, list_profile_ids, load_builtin_profile
from lyraforge.library import (
    LibraryStore,
    default_data_dir,
    export_backup_zip,
    export_lyrapack,
    import_lyrapack,
    resolve_under,
    restore_backup_zip,
)
from lyraforge.media import SUPPORTED_MEDIA_EXTENSIONS, MediaLimits
from lyraforge.music_core.arranger import (
    ArrangeOptions,
    SemitonePolicy,
    Style,
    list_arranger_strategies,
)
from lyraforge.music_core.midi_import import ImportLimits
from lyraforge.pipelines import DEFAULT_PIPELINE_ID, list_pipelines
from lyraforge.playback import (
    LateEventPolicy,
    PlaybackMode,
    analyze_calibration_recording,
    build_calibration_performance,
    is_windows_playback_available,
    list_calibration_patterns,
    run_calibration_benchmark,
)
from lyraforge.presets import list_presets
from lyraforge.preview import (
    DEFAULT_SAMPLE_RATE,
    get_sample_file_path,
    load_sample_manifest,
)
from lyraforge.separators import list_separators
from lyraforge.toolchain import status as toolchain_status
from lyraforge.toolchain import tools_root as toolchain_tools_root
from lyraforge.toolchain.gpu import gpu_status
from lyraforge.toolchain.gpu import set_device as set_dettato_device
from lyraforge.transcribers import DEFAULT_TRANSCRIBER_ID, TranscribeOptions, list_transcribers

SESSION_TOKEN_HEADER = "X-LyraForge-Token"

_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.SOURCE_UNAVAILABLE: 404,
    ErrorCode.PERMISSION_REQUIRED: 403,
    ErrorCode.PLAYBACK_ABORTED: 409,
    ErrorCode.GAME_NOT_FOCUSED: 409,
    ErrorCode.LIMIT_EXCEEDED: 413,
    ErrorCode.MEDIA_DECODE_FAILED: 400,
    ErrorCode.MEDIA_UNSUPPORTED: 400,
    ErrorCode.NO_PLAYABLE_NOTES: 400,
    ErrorCode.PROFILE_INVALID: 400,
    ErrorCode.PERFORMANCE_INVALID: 400,
    ErrorCode.INVALID_ARGUMENT: 400,
    ErrorCode.PACKAGE_INVALID: 400,
    ErrorCode.LIBRARY_BUSY: 409,
    ErrorCode.MODEL_MISSING: 503,
    ErrorCode.TRANSCRIPTION_FAILED: 422,
}


class _LibraryAccessGate:
    """Coordinates shared library access against exclusive restore/shutdown maintenance."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active_ops = 0
        self._maintenance_reason: str | None = None
        self._shutting_down = False

    @property
    def maintenance_reason(self) -> str | None:
        with self._cond:
            return self._maintenance_reason

    @contextmanager
    def use(self) -> Iterator[None]:
        with self._cond:
            if self._shutting_down or self._maintenance_reason is not None:
                reason = self._maintenance_reason or "server_shutdown"
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY,
                    f"library temporarily unavailable ({reason})",
                    {"reason": reason},
                )
            self._active_ops += 1
        try:
            yield
        finally:
            with self._cond:
                self._active_ops -= 1
                self._cond.notify_all()

    @contextmanager
    def exclusive(self, reason: str, *, wait_ops_timeout_s: float = 5.0) -> Iterator[None]:
        deadline = time.monotonic() + max(0.0, float(wait_ops_timeout_s))
        with self._cond:
            if self._shutting_down or self._maintenance_reason is not None:
                active_reason = self._maintenance_reason or "server_shutdown"
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY,
                    f"library maintenance already in progress ({active_reason})",
                    {"reason": active_reason},
                )
            self._maintenance_reason = reason
            while self._active_ops > 0:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    self._maintenance_reason = None
                    self._cond.notify_all()
                    raise LyraError(
                        ErrorCode.LIBRARY_BUSY,
                        f"library busy: timed out waiting for {self._active_ops} operation(s)",
                        {"active_ops": self._active_ops},
                    )
                self._cond.wait(timeout=rem)
        try:
            yield
        finally:
            with self._cond:
                if self._maintenance_reason == reason:
                    self._maintenance_reason = None
                self._cond.notify_all()

    def begin_shutdown(self, *, wait_ops_timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + max(0.0, float(wait_ops_timeout_s))
        with self._cond:
            self._shutting_down = True
            while self._maintenance_reason is not None:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(timeout=rem)
            self._maintenance_reason = "server_shutdown"
            while self._active_ops > 0:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(timeout=rem)
            self._cond.notify_all()


class TranscribeJobRequest(BaseModel):
    song_id: str
    engine_id: str = DEFAULT_TRANSCRIBER_ID
    pipeline_id: str = DEFAULT_PIPELINE_ID
    vocal_engine_id: str | None = None
    accomp_engine_id: str | None = None
    vocal_cleanup: str = "standard"
    vocal_range: str = "auto"
    min_pitch: int = 36
    max_pitch: int = 96
    min_note_ms: int = 60
    onset_threshold: float | None = None
    frame_threshold: float | None = None
    async_mode: bool = False


class SettingUpdateRequest(BaseModel):
    key: str
    value: Any


class ArrangeVariantConfig(BaseModel):
    style: Style = Style.BALANCED
    transpose: int | None = None
    semitone_policy: SemitonePolicy = SemitonePolicy.NEAREST
    max_chord_keys: int | None = None
    chord_window_ms: int = 20
    speed: float = 1.0
    include_tracks: list[int] | None = None
    exclude_percussion: bool = True
    arpeggiate_ms: int = 0
    prefer_melody_track: bool = True
    arranger_strategy: str = "classic"
    melody_track: int | None = None
    vocal_ducking: bool = True
    melody_ceiling: bool = True
    anti_clash_semitones: bool = True
    timing_mode: str = "adapted"
    accomp_density: str | None = None
    phrase_octave_mode: str | None = None
    cross_stem_align_ms: int | None = Field(default=None, ge=0, le=60)
    transcription_id: str | None = None
    label: str | None = None


class ArrangeJobRequest(ArrangeVariantConfig):
    song_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID


class ArrangeABRequest(BaseModel):
    song_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID
    transcription_id: str | None = None
    variant_a: ArrangeVariantConfig | None = None
    variant_b: ArrangeVariantConfig | None = None


class EditArrangementRequest(BaseModel):
    events: list[dict[str, Any]]
    label: str | None = None


class FavoriteRequest(BaseModel):
    is_favorite: bool


class VoteRequest(BaseModel):
    vote: int


class CompareArrangementsRequest(BaseModel):
    arrangement_a_id: str
    arrangement_b_id: str


class LyrapackExportRequest(BaseModel):
    copyright_confirmed: bool = False
    license_notice: str = ""


class AgentRunRequest(BaseModel):
    prompt: str
    song_id: str | None = None
    arrangement_id: str | None = None
    allow_network: bool = False
    local_path: str | None = None
    source_url: str | None = None


class PreviewRequest(BaseModel):
    arrangement_id: str
    sample_rate: int = DEFAULT_SAMPLE_RATE
    fixed_velocity: bool = False
    timbre: str = "auto"


class PlaybackPrepareRequest(BaseModel):
    arrangement_id: str
    mode: PlaybackMode = PlaybackMode.DRY_RUN
    realtime: bool = False
    allowed_window_titles: list[str] | None = Field(default=None)
    allowed_processes: list[str] | None = Field(default=None)
    min_key_release_gap_ms: int | None = Field(default=None, ge=0, le=500)
    key_hold_ms: int | None = Field(default=None, ge=1, le=2000)
    late_event_policy: LateEventPolicy = LateEventPolicy.SHIFT_CLOCK
    late_threshold_ms: int = Field(default=25, ge=1, le=1000)
    record_trace: bool = False


class CalibrationRunRequest(BaseModel):
    pattern_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID
    realtime: bool = False
    duration_s: float | None = Field(default=None, ge=1.0, le=180.0)


class CalibrationPrepareRequest(BaseModel):
    pattern_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID
    mode: PlaybackMode = PlaybackMode.DRY_RUN
    realtime: bool = False
    duration_s: float | None = Field(default=None, ge=1.0, le=180.0)
    allowed_window_titles: list[str] | None = Field(default=None)
    allowed_processes: list[str] | None = Field(default=None)
    min_key_release_gap_ms: int | None = Field(default=None, ge=0, le=500)
    key_hold_ms: int | None = Field(default=None, ge=1, le=2000)
    late_event_policy: LateEventPolicy = LateEventPolicy.SHIFT_CLOCK


class PlaybackStartRequest(BaseModel):
    prepare_token: str
    wait_for_focus_s: float = Field(default=10.0, ge=0.0, le=30.0)


class HotkeyBindingModel(BaseModel):
    action: str
    text: str = ""


class HotkeysUpdateRequest(BaseModel):
    bindings: list[HotkeyBindingModel] = Field(default_factory=list)


class ArrangementLabelRequest(BaseModel):
    label: str = Field(default="", max_length=80)


class DettatoDeviceRequest(BaseModel):
    device: str = "auto"


class QueueSetRequest(BaseModel):
    arrangement_ids: list[str] = Field(default_factory=list)
    start_index: int = 0
    mode: PlaybackMode = PlaybackMode.DRY_RUN
    realtime: bool = False


class QueueAddRequest(BaseModel):
    arrangement_id: str


class QueueStepRequest(BaseModel):
    delta: int = 1


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def default_web_dist_dir() -> Path | None:
    """Locate built Vite frontend assets in a PyInstaller bundle or source checkout."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "apps" / "desktop" / "web" / "dist"
        if (bundled / "index.html").is_file():
            return bundled
    candidate = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "web" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _render_bootstrap_html(index_path: Path, session_token: str) -> str:
    html = index_path.read_text(encoding="utf-8")
    payload = json.dumps({"apiBase": "", "sessionToken": session_token}).replace("</", "<\\/")
    snippet = f"<script>window.__LYRAFORGE_CONFIG__={payload};</script>"
    if "</head>" in html:
        return html.replace("</head>", f"{snippet}</head>", 1)
    return snippet + html


def create_app(
    *,
    data_dir: str | Path | None = None,
    session_token: str | None = None,
    cors_origins: Sequence[str] = (),
    static_dir: str | Path | None = None,
) -> FastAPI:
    resolved_dir = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
    token = session_token or secrets.token_urlsafe(32)
    manager = PlaybackManager()
    job_manager = TranscriptionJobManager()
    tool_manager = ToolInstallManager()
    queue_manager = PlaybackQueueManager()
    library_gate = _LibraryAccessGate()

    def _hotkey_start() -> None:
        with suppress(LyraError):
            manager.start_pending(data_dir=resolved_dir, wait_for_focus_s=5.0)

    def _hotkey_pause() -> None:
        with suppress(LyraError):
            manager.pause()

    def _hotkey_resume() -> None:
        with suppress(LyraError):
            manager.resume()

    def _hotkey_stop() -> None:
        with suppress(LyraError):
            manager.stop("hotkey_stop")

    def _hotkey_next() -> None:
        with suppress(Exception):
            _step_queue(1)

    def _hotkey_previous() -> None:
        with suppress(Exception):
            _step_queue(-1)

    hotkey_registry = HotkeyRegistry(
        {
            "start": _hotkey_start,
            "pause": _hotkey_pause,
            "resume": _hotkey_resume,
            "stop": _hotkey_stop,
            "next": _hotkey_next,
            "previous": _hotkey_previous,
        }
    )

    @contextmanager
    def open_store() -> Iterator[LibraryStore]:
        with library_gate.use(), LibraryStore(app.state.data_dir) as store:
            yield store

    def _queue_item(store: LibraryStore, arrangement_id: str) -> QueueItem:
        rec = store.get_arrangement(arrangement_id)
        song = store.get_song(rec.song_id).song
        return QueueItem(
            arrangement_id=rec.id,
            label=f"{song.title} · {rec.style}",
        )

    def _step_queue(delta: int) -> dict[str, Any]:
        with open_store() as store:
            item = queue_manager.step(delta)
            if item is None:
                return {
                    "queue": queue_manager.snapshot(),
                    "playback": manager.status(),
                }
            if manager.is_active():
                manager.stop("queue_switch", timeout_s=2.0)
            snapshot = queue_manager.snapshot()
            manager.prepare(
                item.arrangement_id,
                mode=PlaybackMode(str(snapshot["mode"])),
                realtime=bool(snapshot["realtime"]),
                store=store,
            )
            started = manager.start_pending(
                data_dir=resolved_dir, wait_for_focus_s=5.0
            )
            return {"queue": queue_manager.snapshot(), "playback": started}

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            raw_hotkeys = None
            try:
                with LibraryStore(resolved_dir) as store:
                    raw_hotkeys = store.get_settings().get("windows_hotkeys")
            except Exception:  # pragma: no cover - settings load must not block startup
                raw_hotkeys = None
            if isinstance(raw_hotkeys, list):
                mapping = {
                    str(item.get("action")): str(item.get("text") or "")
                    for item in raw_hotkeys
                    if isinstance(item, dict) and item.get("action")
                }
                if mapping:
                    hotkey_registry.apply(mapping)
            yield
        finally:
            hotkey_registry.stop()
            timeout_s = float(getattr(app.state, "restore_drain_timeout_s", 5.0))
            library_gate.begin_shutdown(wait_ops_timeout_s=timeout_s)
            job_manager.pause_submissions("server_shutdown")
            manager.stop("server_shutdown", timeout_s=timeout_s)
            job_manager.cancel_all("server_shutdown", timeout_s=timeout_s, pause_new=True)

    app = FastAPI(title="LyraForge Local API", version=__version__, lifespan=_lifespan)
    app.state.data_dir = resolved_dir
    app.state.session_token = token
    app.state.playback_manager = manager
    app.state.job_manager = job_manager
    app.state.tool_manager = tool_manager
    app.state.hotkeys = hotkey_registry
    app.state.library_gate = library_gate
    app.state.restore_drain_timeout_s = 5.0

    origins = [o for o in cors_origins if o and o != "*"]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=[SESSION_TOKEN_HEADER, "Content-Type"],
        )

    @app.exception_handler(LyraError)
    async def _lyra_error_handler(_request: Request, exc: LyraError) -> JSONResponse:
        status = _STATUS_MAP.get(exc.code, 500)
        return JSONResponse(status_code=status, content={"error": exc.to_dict()})

    def require_token(
        x_lyraforge_token: str | None = Header(default=None, alias=SESSION_TOKEN_HEADER),
    ) -> None:
        if not x_lyraforge_token or not secrets.compare_digest(x_lyraforge_token, token):
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "missing or invalid session token"},
            )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "platform": sys.platform,
            "windows_playback_available": is_windows_playback_available(),
        }

    @app.get("/v1/profiles", dependencies=[Depends(require_token)])
    def get_profiles() -> dict[str, Any]:
        items = []
        for pid in list_profile_ids():
            p = load_builtin_profile(pid)
            items.append(
                {
                    "id": p.id,
                    "display_name": p.display_name,
                    "game_id": p.game_id,
                    "kind": p.kind,
                    "key_count": len(p.keys),
                    "min_pitch": p.min_pitch,
                    "max_pitch": p.max_pitch,
                    "calibration_status": p.calibration_status,
                    "hash": p.hash,
                }
            )
        return {"profiles": items}

    @app.get("/v1/profiles/{profile_id}", dependencies=[Depends(require_token)])
    def get_profile(profile_id: str) -> dict[str, Any]:
        p = load_builtin_profile(profile_id)
        data = dict(p.raw)
        data["_hash"] = p.hash
        return data

    @app.post("/v1/imports", dependencies=[Depends(require_token)])
    async def import_media(
        file: UploadFile = File(...),  # noqa: B008
        title: str | None = Form(default=None),
        artist: str = Form(default=""),
        tags: str = Form(default=""),
    ) -> dict[str, Any]:
        orig_name = Path(file.filename or "upload.mid").name
        ext = Path(orig_name).suffix.lower()
        is_audio = ext in SUPPORTED_MEDIA_EXTENSIONS
        max_bytes = (
            MediaLimits().max_file_bytes if is_audio else ImportLimits().max_file_bytes
        )
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise LyraError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"uploaded file exceeds limit ({max_bytes} bytes)",
                    {"limit": max_bytes},
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
        clean_title = (title or "").strip() or Path(orig_name).stem

        with tempfile.TemporaryDirectory(prefix="lyraforge-import-") as tmpdir:
            tmp_file = Path(tmpdir) / orig_name
            tmp_file.write_bytes(raw)
            with open_store() as store:
                if is_audio:
                    res = store.import_audio(
                        tmp_file,
                        title=clean_title,
                        artist=artist,
                        tags=_parse_tags(tags),
                    )
                else:
                    res = store.import_midi(
                        tmp_file,
                        title=clean_title,
                        artist=artist,
                        tags=_parse_tags(tags),
                    )
        return res.to_json()

    @app.get("/v1/library/songs", dependencies=[Depends(require_token)])
    def list_songs(
        q: str = Query(default=""),
        tag: str = Query(default=""),
        favorites_only: bool = Query(default=False),
    ) -> dict[str, Any]:
        with open_store() as store:
            songs = [
                s.to_json()
                for s in store.search_songs(
                    q, tag=tag or None, favorites_only=favorites_only
                )
            ]
        return {"songs": songs}

    @app.get("/v1/library/backup.zip", dependencies=[Depends(require_token)])
    def download_library_backup() -> Response:
        with open_store() as store:
            data = export_backup_zip(store)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="lyraforge-backup.zip"'},
        )

    @app.post("/v1/library/restore", dependencies=[Depends(require_token)])
    async def restore_library_backup(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        max_bytes = 250 * 1024 * 1024
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise LyraError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"backup archive exceeds limit ({max_bytes} bytes)",
                )
            chunks.append(chunk)
        archive_bytes = b"".join(chunks)

        def _do_restore() -> dict[str, Any]:
            drain_timeout = float(getattr(app.state, "restore_drain_timeout_s", 5.0))
            with library_gate.exclusive("library_restore", wait_ops_timeout_s=drain_timeout):
                job_manager.pause_submissions("library_restore")
                try:
                    manager.stop("library_restore", timeout_s=drain_timeout)
                    if manager.is_active():
                        raise LyraError(
                            ErrorCode.LIBRARY_BUSY,
                            "cannot restore library: active playback session failed to stop",
                        )
                    surviving = job_manager.cancel_all(
                        "library_restore",
                        timeout_s=drain_timeout,
                        pause_new=True,
                    )
                    if surviving:
                        raise LyraError(
                            ErrorCode.LIBRARY_BUSY,
                            "cannot restore library: background transcription job(s) "
                            f"did not terminate cleanly ({surviving})",
                            {"active_jobs": surviving},
                        )
                    summary = restore_backup_zip(app.state.data_dir, archive_bytes)
                    return {"restored": summary}
                finally:
                    if library_gate.maintenance_reason != "server_shutdown":
                        job_manager.resume_submissions()

        return await anyio.to_thread.run_sync(_do_restore)

    @app.post("/v1/imports/lyrapack", dependencies=[Depends(require_token)])
    async def import_lyrapack_route(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        max_bytes = 25 * 1024 * 1024
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise LyraError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f".lyrapack upload exceeds limit ({max_bytes} bytes)",
                )
            chunks.append(chunk)
        with open_store() as store:
            return import_lyrapack(store, b"".join(chunks))

    @app.get("/v1/library/songs/{song_id}", dependencies=[Depends(require_token)])
    def get_song(song_id: str) -> dict[str, Any]:
        with open_store() as store:
            return store.get_song(song_id).to_json()

    @app.get("/v1/library/songs/{song_id}/tracks", dependencies=[Depends(require_token)])
    def get_song_tracks_route(
        song_id: str,
        transcription_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        with open_store() as store:
            return store.get_song_tracks(song_id, transcription_id=transcription_id)

    @app.get("/v1/transcribers", dependencies=[Depends(require_token)])
    def get_transcribers() -> dict[str, Any]:
        return {"transcribers": [m.to_json() for m in list_transcribers()]}

    @app.get("/v1/pipelines", dependencies=[Depends(require_token)])
    def get_pipelines_route() -> dict[str, Any]:
        return {"pipelines": [p.to_json() for p in list_pipelines()]}

    @app.get("/v1/separators", dependencies=[Depends(require_token)])
    def get_separators_route() -> dict[str, Any]:
        return {"separators": [s.to_json() for s in list_separators()]}

    @app.get("/v1/arrangers", dependencies=[Depends(require_token)])
    def get_arrangers_route() -> dict[str, Any]:
        return {"strategies": [s.to_json() for s in list_arranger_strategies()]}

    @app.get("/v1/presets", dependencies=[Depends(require_token)])
    def get_presets(profile_id: str | None = Query(default=None)) -> dict[str, Any]:
        return {"presets": list_presets(profile_id)}

    @app.get("/v1/tools", dependencies=[Depends(require_token)])
    def get_tools() -> dict[str, Any]:
        return {
            "tools_dir": str(toolchain_tools_root()),
            "tools": toolchain_status(),
            "installs": tool_manager.snapshot(),
        }

    @app.post("/v1/tools/{tool_id}/install", dependencies=[Depends(require_token)])
    def install_tool(tool_id: str) -> dict[str, Any]:
        return {"install": tool_manager.start(tool_id)}

    @app.get("/v1/gpu", dependencies=[Depends(require_token)])
    def get_gpu_status() -> dict[str, Any]:
        return gpu_status()

    @app.post("/v1/gpu/device", dependencies=[Depends(require_token)])
    def set_gpu_device(req: DettatoDeviceRequest) -> dict[str, Any]:
        return set_dettato_device(req.device)

    @app.post("/v1/gpu/install", dependencies=[Depends(require_token)])
    def install_gpu_torch(tool_id: str = Query(default="dettato")) -> dict[str, Any]:
        if tool_id == "dettato":
            return {"install": tool_manager.start("dettato-gpu")}
        if tool_id == "demucs":
            return {"install": tool_manager.start("demucs-gpu")}
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported GPU target: {tool_id!r}",
            {"supported": ["dettato", "demucs"]},
        )

    @app.post("/v1/gpu/install/demucs", dependencies=[Depends(require_token)])
    def install_demucs_gpu_torch() -> dict[str, Any]:
        return {"install": tool_manager.start("demucs-gpu")}

    def _variant_to_arrange_options(v: ArrangeVariantConfig) -> ArrangeOptions:
        return ArrangeOptions(
            style=v.style,
            transpose=v.transpose,
            semitone_policy=v.semitone_policy,
            max_chord_keys=v.max_chord_keys,
            chord_window_ms=v.chord_window_ms,
            speed=v.speed,
            include_tracks=tuple(v.include_tracks) if v.include_tracks is not None else None,
            exclude_percussion=v.exclude_percussion,
            arpeggiate_ms=v.arpeggiate_ms,
            prefer_melody_track=v.prefer_melody_track,
            arranger_strategy=v.arranger_strategy,
            melody_track=v.melody_track,
            vocal_ducking=v.vocal_ducking,
            melody_ceiling=v.melody_ceiling,
            anti_clash_semitones=v.anti_clash_semitones,
            timing_mode=v.timing_mode,
            accomp_density=v.accomp_density,
            phrase_octave_mode=v.phrase_octave_mode,
            cross_stem_align_ms=v.cross_stem_align_ms,
        )

    @app.post("/v1/jobs/transcribe", dependencies=[Depends(require_token)])
    def transcribe_job(req: TranscribeJobRequest) -> dict[str, Any]:
        opts = TranscribeOptions(
            min_pitch=req.min_pitch,
            max_pitch=req.max_pitch,
            min_note_ms=req.min_note_ms,
            onset_threshold=req.onset_threshold,
            frame_threshold=req.frame_threshold,
        )
        if req.async_mode:
            with library_gate.use():
                job = job_manager.submit(
                    req.song_id,
                    engine_id=req.engine_id,
                    pipeline_id=req.pipeline_id,
                    vocal_engine_id=req.vocal_engine_id,
                    accomp_engine_id=req.accomp_engine_id,
                    vocal_cleanup=req.vocal_cleanup,
                    vocal_range=req.vocal_range,
                    options=opts,
                    data_dir=app.state.data_dir,
                )
            return {"job": job}
        with open_store() as store:
            rec = store.transcribe_song(
                req.song_id,
                engine_id=req.engine_id,
                pipeline_id=req.pipeline_id,
                vocal_engine_id=req.vocal_engine_id,
                accomp_engine_id=req.accomp_engine_id,
                vocal_cleanup=req.vocal_cleanup,
                vocal_range=req.vocal_range,
                options=opts,
            )
        return {"transcription": rec.to_json()}

    @app.get("/v1/jobs", dependencies=[Depends(require_token)])
    def list_jobs() -> dict[str, Any]:
        return {"jobs": job_manager.list_jobs()}

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
    def get_job(job_id: str) -> dict[str, Any]:
        return {"job": job_manager.get(job_id)}

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
    def cancel_job(job_id: str) -> dict[str, Any]:
        return {"job": job_manager.cancel(job_id)}

    @app.post("/v1/jobs/arrange", dependencies=[Depends(require_token)])
    def arrange_job(req: ArrangeJobRequest) -> dict[str, Any]:
        opts = _variant_to_arrange_options(req)
        with open_store() as store:
            rec, created = store.arrange_song_with_status(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=opts,
                label=req.label,
                transcription_id=req.transcription_id,
            )
        return {"arrangement": rec.to_json(), "created": created}

    @app.post("/v1/studio/preview-arrange", dependencies=[Depends(require_token)])
    def preview_arrange_route(req: ArrangeJobRequest) -> dict[str, Any]:
        opts = _variant_to_arrange_options(req)
        with open_store() as store:
            return store.preview_arrange(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=opts,
                transcription_id=req.transcription_id,
            )

    @app.post("/v1/jobs/arrange-ab", dependencies=[Depends(require_token)])
    def arrange_ab_job(req: ArrangeABRequest) -> dict[str, Any]:
        va = req.variant_a or ArrangeVariantConfig(
            style=Style.BALANCED,
            arpeggiate_ms=0,
            arranger_strategy="classic",
            label="A · 经典基线",
        )
        vb = req.variant_b or ArrangeVariantConfig(
            style=Style.BALANCED,
            arpeggiate_ms=0,
            arranger_strategy="vocal_lead",
            label="B · 主旋律增强",
        )

        with open_store() as store:
            rec_a = store.arrange_song(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=_variant_to_arrange_options(va),
                label=va.label or "A",
                transcription_id=va.transcription_id or req.transcription_id,
            )
            rec_b = store.arrange_song(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=_variant_to_arrange_options(vb),
                label=vb.label or "B",
                transcription_id=vb.transcription_id or req.transcription_id,
            )
            diff = store.compare_arrangements(rec_a.id, rec_b.id)
        return {
            "arrangement_a": rec_a.to_json(),
            "arrangement_b": rec_b.to_json(),
            "comparison": diff,
        }

    @app.post("/v1/arrangements/compare", dependencies=[Depends(require_token)])
    def compare_arrangements_route(req: CompareArrangementsRequest) -> dict[str, Any]:
        with open_store() as store:
            return store.compare_arrangements(req.arrangement_a_id, req.arrangement_b_id)

    @app.post("/v1/arrangements/{arrangement_id}/edit", dependencies=[Depends(require_token)])
    def edit_arrangement_route(
        arrangement_id: str, req: EditArrangementRequest
    ) -> dict[str, Any]:
        with open_store() as store:
            rec = store.save_edited_arrangement(arrangement_id, req.events, label=req.label)
        return {"arrangement": rec.to_json()}

    @app.post("/v1/arrangements/{arrangement_id}/label", dependencies=[Depends(require_token)])
    def set_arrangement_label_route(
        arrangement_id: str, req: ArrangementLabelRequest
    ) -> dict[str, Any]:
        with open_store() as store:
            rec = store.set_arrangement_label(arrangement_id, req.label)
        return {"arrangement": rec.to_json()}

    @app.post("/v1/arrangements/{arrangement_id}/favorite", dependencies=[Depends(require_token)])
    def favorite_arrangement_route(
        arrangement_id: str, req: FavoriteRequest
    ) -> dict[str, Any]:
        with open_store() as store:
            rec = store.set_favorite(arrangement_id, req.is_favorite)
        return {"arrangement": rec.to_json()}

    @app.post("/v1/arrangements/{arrangement_id}/vote", dependencies=[Depends(require_token)])
    def vote_arrangement_route(arrangement_id: str, req: VoteRequest) -> dict[str, Any]:
        with open_store() as store:
            rec = store.set_user_vote(arrangement_id, req.vote)
        return {"arrangement": rec.to_json()}

    @app.get("/v1/arrangements/{arrangement_id}", dependencies=[Depends(require_token)])
    def get_arrangement(arrangement_id: str) -> dict[str, Any]:
        with open_store() as store:
            rec = store.get_arrangement(arrangement_id)
            perf = store.load_arrangement_performance(arrangement_id)
            rep_path = resolve_under(store.data_dir, rec.report_path)
            report = (
                json.loads(rep_path.read_text(encoding="utf-8"))
                if rep_path.is_file()
                else None
            )
        return {"arrangement": rec.to_json(), "performance": perf, "report": report}

    @app.delete("/v1/arrangements/{arrangement_id}", dependencies=[Depends(require_token)])
    def delete_arrangement_route(arrangement_id: str) -> dict[str, Any]:
        with open_store() as store:
            res = store.delete_arrangement(arrangement_id)
        queue_manager.remove_arrangement(arrangement_id)
        return {**res, "queue": queue_manager.snapshot()}

    @app.get("/v1/preview/samples/manifest", dependencies=[Depends(require_token)])
    def get_preview_samples_manifest() -> dict[str, Any]:
        return load_sample_manifest()

    @app.get("/v1/preview/samples/{pack}/{filename}", dependencies=[Depends(require_token)])
    def get_preview_sample_wav(pack: str, filename: str) -> Response:
        wav_path = get_sample_file_path(pack, filename)
        return Response(
            content=wav_path.read_bytes(),
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.post("/v1/preview", dependencies=[Depends(require_token)])
    def render_preview(req: PreviewRequest) -> dict[str, Any]:
        with open_store() as store:
            wav_path = store.render_preview(
                req.arrangement_id,
                sample_rate=req.sample_rate,
                fixed_velocity=req.fixed_velocity,
                timbre=req.timbre,
            )
            size_bytes = wav_path.stat().st_size
        params: list[str] = []
        if req.fixed_velocity:
            params.append("fixed_velocity=1")
        clean_timbre = (req.timbre or "auto").strip().lower()
        if clean_timbre != "auto":
            params.append(f"timbre={clean_timbre}")
        q = f"?{'&'.join(params)}" if params else ""
        return {
            "arrangement_id": req.arrangement_id,
            "preview_url": f"/v1/arrangements/{req.arrangement_id}/preview.wav{q}",
            "size_bytes": size_bytes,
            "sample_rate": req.sample_rate,
            "fixed_velocity": req.fixed_velocity,
            "timbre": clean_timbre,
        }

    @app.get(
        "/v1/arrangements/{arrangement_id}/preview.wav",
        dependencies=[Depends(require_token)],
    )
    def get_preview_wav(
        arrangement_id: str,
        fixed_velocity: bool = False,
        timbre: str = "auto",
    ) -> Response:
        with open_store() as store:
            rec = store.get_arrangement(arrangement_id)
            clean_timbre = (timbre or "auto").strip().lower()
            cache_rel = store.preview_cache_rel_path(
                rec.song_id,
                rec.id,
                fixed_velocity=fixed_velocity,
                timbre=clean_timbre,
            )
            wav_path: Path | None = None
            candidate = resolve_under(store.data_dir, cache_rel)
            if candidate.is_file():
                wav_path = candidate
            elif not fixed_velocity and clean_timbre == "auto" and rec.preview_path:
                legacy = resolve_under(store.data_dir, rec.preview_path)
                if legacy.is_file():
                    wav_path = legacy
            if wav_path is None:
                wav_path = store.render_preview(
                    arrangement_id,
                    fixed_velocity=fixed_velocity,
                    timbre=clean_timbre,
                )
            data = wav_path.read_bytes()
        return Response(content=data, media_type="audio/wav")

    @app.get(
        "/v1/arrangements/{arrangement_id}/export.mid",
        dependencies=[Depends(require_token)],
    )
    def export_arrangement_midi(arrangement_id: str) -> Response:
        with open_store() as store:
            data = store.export_arrangement(arrangement_id, "midi")
        return Response(
            content=data,
            media_type="audio/midi",
            headers={"Content-Disposition": f'attachment; filename="{arrangement_id}.mid"'},
        )

    @app.get(
        "/v1/arrangements/{arrangement_id}/export.json",
        dependencies=[Depends(require_token)],
    )
    def export_arrangement_json(arrangement_id: str) -> Response:
        with open_store() as store:
            data = store.export_arrangement(arrangement_id, "json")
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{arrangement_id}.json"'},
        )

    @app.post(
        "/v1/arrangements/{arrangement_id}/export.lyrapack",
        dependencies=[Depends(require_token)],
    )
    def export_arrangement_lyrapack(
        arrangement_id: str, req: LyrapackExportRequest
    ) -> Response:
        with open_store() as store:
            data = export_lyrapack(
                store,
                arrangement_id,
                copyright_confirmed=req.copyright_confirmed,
                license_notice=req.license_notice,
            )
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{arrangement_id}.lyrapack"'},
        )

    @app.get("/v1/settings", dependencies=[Depends(require_token)])
    def get_settings() -> dict[str, Any]:
        with open_store() as store:
            return {"settings": store.get_settings()}

    @app.get("/v1/agent/tools", dependencies=[Depends(require_token)])
    def get_agent_tools() -> dict[str, Any]:
        return {
            "allowed_tools": list(ALLOWED_TOOLS),
            "forbidden_tools": list(FORBIDDEN_TOOLS),
        }

    @app.post("/v1/agent/run", dependencies=[Depends(require_token)])
    def run_agent(req: AgentRunRequest) -> dict[str, Any]:
        with open_store() as store:
            settings = store.get_settings()
            raw_dirs = settings.get("local_search_dirs")
            search_dirs = (
                [str(d) for d in raw_dirs if isinstance(d, str) and d.strip()]
                if isinstance(raw_dirs, list)
                else []
            )
            orch = AgentOrchestrator(store, search_dirs=search_dirs)
            result = orch.run(
                req.prompt,
                song_id=req.song_id,
                arrangement_id=req.arrangement_id,
                allow_network=req.allow_network,
                local_path=req.local_path,
                source_url=req.source_url,
            )
        return result.to_json()

    @app.post("/v1/settings", dependencies=[Depends(require_token)])
    def update_setting(req: SettingUpdateRequest) -> dict[str, Any]:
        with open_store() as store:
            store.set_setting(req.key, req.value)
            return {"settings": store.get_settings()}

    @app.get("/v1/hotkeys", dependencies=[Depends(require_token)])
    def get_hotkeys() -> dict[str, Any]:
        return {
            "supported": hotkey_registry.supported(),
            "bindings": hotkey_registry.bindings,
            "errors": hotkey_registry.errors,
            "actions": [
                {"id": action, "label": ACTION_LABELS[action]} for action in HOTKEY_ACTIONS
            ],
        }

    @app.post("/v1/hotkeys", dependencies=[Depends(require_token)])
    def set_hotkeys(req: HotkeysUpdateRequest) -> dict[str, Any]:
        mapping = {binding.action: binding.text for binding in req.bindings}
        errors = hotkey_registry.apply(mapping)
        with open_store() as store:
            store.set_setting(
                "windows_hotkeys", [binding.model_dump() for binding in req.bindings]
            )
        return {
            "supported": hotkey_registry.supported(),
            "bindings": hotkey_registry.bindings,
            "errors": errors,
        }

    @app.post("/v1/app/relaunch-elevated", dependencies=[Depends(require_token)])
    def relaunch_elevated_app() -> dict[str, Any]:
        from lyraforge.elevation import relaunch_elevated

        return {"relaunched": relaunch_elevated()}

    @app.get("/v1/playback/queue", dependencies=[Depends(require_token)])
    def get_playback_queue() -> dict[str, Any]:
        return queue_manager.snapshot()

    @app.post("/v1/playback/queue", dependencies=[Depends(require_token)])
    def set_playback_queue(req: QueueSetRequest) -> dict[str, Any]:
        with open_store() as store:
            items = [_queue_item(store, arrangement_id) for arrangement_id in req.arrangement_ids]
        queue_manager.set_items(
            items,
            start_index=req.start_index,
            mode=req.mode,
            realtime=req.realtime,
        )
        return queue_manager.snapshot()

    @app.post("/v1/playback/queue/add", dependencies=[Depends(require_token)])
    def add_playback_queue_item(req: QueueAddRequest) -> dict[str, Any]:
        with open_store() as store:
            queue_manager.add(_queue_item(store, req.arrangement_id))
        return queue_manager.snapshot()

    @app.post("/v1/playback/queue/clear", dependencies=[Depends(require_token)])
    def clear_playback_queue() -> dict[str, Any]:
        queue_manager.clear()
        return queue_manager.snapshot()

    @app.post("/v1/playback/queue/step", dependencies=[Depends(require_token)])
    def step_playback_queue(req: QueueStepRequest) -> dict[str, Any]:
        return _step_queue(req.delta)

    def _resolve_window_allowlists(
        store: LibraryStore,
        req_titles: list[str] | None,
        req_processes: list[str] | None,
    ) -> tuple[list[str] | None, list[str] | None]:
        settings = store.get_settings()
        allowed_titles = req_titles
        if allowed_titles is None:
            raw_titles = settings.get("windows_allowed_titles")
            if isinstance(raw_titles, str):
                allowed_titles = [t.strip() for t in raw_titles.split(",") if t.strip()] or None
            elif isinstance(raw_titles, list):
                allowed_titles = [str(t).strip() for t in raw_titles if str(t).strip()] or None
        allowed_processes = req_processes
        if allowed_processes is None:
            raw_processes = settings.get("windows_allowed_processes")
            if isinstance(raw_processes, str):
                allowed_processes = (
                    [p.strip() for p in raw_processes.split(",") if p.strip()] or None
                )
            elif isinstance(raw_processes, list):
                allowed_processes = (
                    [str(p).strip() for p in raw_processes if str(p).strip()] or None
                )
        return allowed_titles, allowed_processes

    @app.post("/v1/playback/prepare", dependencies=[Depends(require_token)])
    def playback_prepare(req: PlaybackPrepareRequest) -> dict[str, Any]:
        with open_store() as store:
            allowed_titles, allowed_processes = _resolve_window_allowlists(
                store, req.allowed_window_titles, req.allowed_processes
            )
            return manager.prepare(
                req.arrangement_id,
                mode=req.mode,
                realtime=req.realtime,
                allowed_window_titles=allowed_titles,
                allowed_processes=allowed_processes,
                min_key_release_gap_ms=req.min_key_release_gap_ms,
                key_hold_ms=req.key_hold_ms,
                late_event_policy=req.late_event_policy,
                late_threshold_ms=req.late_threshold_ms,
                record_trace=req.record_trace,
                store=store,
            )

    @app.get("/v1/calibration/patterns", dependencies=[Depends(require_token)])
    def get_calibration_patterns() -> dict[str, Any]:
        return {"patterns": list_calibration_patterns()}

    @app.post("/v1/calibration/run-dry", dependencies=[Depends(require_token)])
    async def run_calibration_dry(req: CalibrationRunRequest) -> dict[str, Any]:
        profile = load_builtin_profile(req.instrument_profile_id)
        return await anyio.to_thread.run_sync(
            lambda: run_calibration_benchmark(
                req.pattern_id,
                profile,
                realtime=req.realtime,
                duration_s=req.duration_s,
            )
        )

    @app.post("/v1/calibration/prepare", dependencies=[Depends(require_token)])
    def prepare_calibration(req: CalibrationPrepareRequest) -> dict[str, Any]:
        profile = load_builtin_profile(req.instrument_profile_id)
        built = build_calibration_performance(
            req.pattern_id, profile, duration_s=req.duration_s
        )
        with open_store() as store:
            allowed_titles, allowed_processes = _resolve_window_allowlists(
                store, req.allowed_window_titles, req.allowed_processes
            )
        prep = manager.prepare_events(
            f"calibration:{req.pattern_id}:{profile.id}",
            doc=built["performance"],
            profile=profile,
            mode=req.mode,
            realtime=req.realtime,
            allowed_window_titles=allowed_titles,
            allowed_processes=allowed_processes,
            min_key_release_gap_ms=req.min_key_release_gap_ms,
            key_hold_ms=req.key_hold_ms,
            late_event_policy=req.late_event_policy,
            record_trace=True,
        )
        return {**prep, "pattern": built["pattern"], "segments": built["segments"]}

    @app.post("/v1/calibration/analyze", dependencies=[Depends(require_token)])
    async def analyze_calibration(
        file: UploadFile = File(...),  # noqa: B008
        pattern_id: str = Form(...),  # noqa: B008
        instrument_profile_id: str = Form(DEFAULT_PROFILE_ID),  # noqa: B008
        tolerance_ms: float = Form(45.0),  # noqa: B008
    ) -> dict[str, Any]:
        max_bytes = 50 * 1024 * 1024
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise LyraError(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"calibration WAV exceeds limit ({max_bytes} bytes)",
                )
            chunks.append(chunk)
        wav_bytes = b"".join(chunks)
        profile = load_builtin_profile(instrument_profile_id)
        built = build_calibration_performance(pattern_id, profile)
        return await anyio.to_thread.run_sync(
            lambda: analyze_calibration_recording(
                wav_bytes,
                built["performance"]["events"],
                pattern_id=pattern_id,
                segments=built["segments"],
                tolerance_ms=tolerance_ms,
            )
        )

    @app.post("/v1/playback/start", dependencies=[Depends(require_token)])
    def playback_start(req: PlaybackStartRequest) -> dict[str, Any]:
        with library_gate.use():
            return manager.start(
                req.prepare_token,
                data_dir=app.state.data_dir,
                wait_for_focus_s=req.wait_for_focus_s,
            )

    @app.post("/v1/playback/pause", dependencies=[Depends(require_token)])
    def playback_pause() -> dict[str, Any]:
        return manager.pause()

    @app.post("/v1/playback/resume", dependencies=[Depends(require_token)])
    def playback_resume() -> dict[str, Any]:
        return manager.resume()

    @app.get("/v1/playback/status", dependencies=[Depends(require_token)])
    def playback_status() -> dict[str, Any]:
        return manager.status()

    @app.post("/v1/playback/stop", dependencies=[Depends(require_token)])
    def playback_stop() -> dict[str, Any]:
        return manager.stop()

    if static_dir is not None:
        static_path = Path(static_dir).expanduser().resolve()
        index_html = static_path / "index.html"
        if index_html.is_file():
            assets_dir = static_path / "assets"
            if assets_dir.is_dir():
                app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

            @app.get("/", include_in_schema=False)
            def serve_index() -> HTMLResponse:
                return HTMLResponse(_render_bootstrap_html(index_html, token))

    return app
