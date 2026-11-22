"""Local FastAPI service (127.0.0.1 + per-session token auth)."""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
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
from lyraforge.errors import ErrorCode, LyraError
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
from lyraforge.music_core.arranger import ArrangeOptions, SemitonePolicy, Style
from lyraforge.music_core.midi_import import ImportLimits
from lyraforge.playback import PlaybackMode, is_windows_playback_available
from lyraforge.preview import DEFAULT_SAMPLE_RATE
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
                if not self._shutting_down and self._maintenance_reason == reason:
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
    min_pitch: int = 36
    max_pitch: int = 96
    min_note_ms: int = 60
    async_mode: bool = False


class SettingUpdateRequest(BaseModel):
    key: str
    value: Any


class ArrangeJobRequest(BaseModel):
    song_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID
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
    label: str | None = None


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
    label: str | None = None


class ArrangeABRequest(BaseModel):
    song_id: str
    instrument_profile_id: str = DEFAULT_PROFILE_ID
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


class PlaybackPrepareRequest(BaseModel):
    arrangement_id: str
    mode: PlaybackMode = PlaybackMode.DRY_RUN
    realtime: bool = False
    allowed_window_titles: list[str] | None = Field(default=None)


class PlaybackStartRequest(BaseModel):
    prepare_token: str


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
    library_gate = _LibraryAccessGate()

    @contextmanager
    def open_store() -> Iterator[LibraryStore]:
        with library_gate.use(), LibraryStore(app.state.data_dir) as store:
            yield store

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
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

    @app.get("/v1/transcribers", dependencies=[Depends(require_token)])
    def get_transcribers() -> dict[str, Any]:
        return {"transcribers": [m.to_json() for m in list_transcribers()]}

    @app.post("/v1/jobs/transcribe", dependencies=[Depends(require_token)])
    def transcribe_job(req: TranscribeJobRequest) -> dict[str, Any]:
        opts = TranscribeOptions(
            min_pitch=req.min_pitch,
            max_pitch=req.max_pitch,
            min_note_ms=req.min_note_ms,
        )
        if req.async_mode:
            with library_gate.use():
                job = job_manager.submit(
                    req.song_id,
                    engine_id=req.engine_id,
                    options=opts,
                    data_dir=app.state.data_dir,
                )
            return {"job": job}
        with open_store() as store:
            rec = store.transcribe_song(req.song_id, engine_id=req.engine_id, options=opts)
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
        opts = ArrangeOptions(
            style=req.style,
            transpose=req.transpose,
            semitone_policy=req.semitone_policy,
            max_chord_keys=req.max_chord_keys,
            chord_window_ms=req.chord_window_ms,
            speed=req.speed,
            include_tracks=tuple(req.include_tracks) if req.include_tracks is not None else None,
            exclude_percussion=req.exclude_percussion,
            arpeggiate_ms=req.arpeggiate_ms,
            prefer_melody_track=req.prefer_melody_track,
        )
        with open_store() as store:
            rec = store.arrange_song(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=opts,
                label=req.label,
            )
        return {"arrangement": rec.to_json()}

    @app.post("/v1/jobs/arrange-ab", dependencies=[Depends(require_token)])
    def arrange_ab_job(req: ArrangeABRequest) -> dict[str, Any]:
        va = req.variant_a or ArrangeVariantConfig(
            style=Style.BALANCED,
            arpeggiate_ms=0,
            label="A · 均衡主旋律",
        )
        vb = req.variant_b or ArrangeVariantConfig(
            style=Style.RICH,
            arpeggiate_ms=20,
            label="B · 丰满琶音",
        )

        def _opts(v: ArrangeVariantConfig) -> ArrangeOptions:
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
            )

        with open_store() as store:
            rec_a = store.arrange_song(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=_opts(va),
                label=va.label or "A",
            )
            rec_b = store.arrange_song(
                req.song_id,
                profile_id=req.instrument_profile_id,
                options=_opts(vb),
                label=vb.label or "B",
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

    @app.post("/v1/preview", dependencies=[Depends(require_token)])
    def render_preview(req: PreviewRequest) -> dict[str, Any]:
        with open_store() as store:
            wav_path = store.render_preview(req.arrangement_id, sample_rate=req.sample_rate)
            size_bytes = wav_path.stat().st_size
        return {
            "arrangement_id": req.arrangement_id,
            "preview_url": f"/v1/arrangements/{req.arrangement_id}/preview.wav",
            "size_bytes": size_bytes,
            "sample_rate": req.sample_rate,
        }

    @app.get(
        "/v1/arrangements/{arrangement_id}/preview.wav",
        dependencies=[Depends(require_token)],
    )
    def get_preview_wav(arrangement_id: str) -> Response:
        with open_store() as store:
            rec = store.get_arrangement(arrangement_id)
            wav_path: Path | None = None
            if rec.preview_path:
                candidate = resolve_under(store.data_dir, rec.preview_path)
                if candidate.is_file():
                    wav_path = candidate
            if wav_path is None:
                wav_path = store.render_preview(arrangement_id)
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

    @app.post("/v1/playback/prepare", dependencies=[Depends(require_token)])
    def playback_prepare(req: PlaybackPrepareRequest) -> dict[str, Any]:
        with open_store() as store:
            allowed_titles = req.allowed_window_titles
            if allowed_titles is None:
                raw_titles = store.get_settings().get("windows_allowed_titles")
                if isinstance(raw_titles, str):
                    parsed_titles = [t.strip() for t in raw_titles.split(",") if t.strip()]
                    allowed_titles = parsed_titles or None
                elif isinstance(raw_titles, list):
                    parsed_titles = [str(t).strip() for t in raw_titles if str(t).strip()]
                    allowed_titles = parsed_titles or None
            return manager.prepare(
                req.arrangement_id,
                mode=req.mode,
                realtime=req.realtime,
                allowed_window_titles=allowed_titles,
                store=store,
            )

    @app.post("/v1/playback/start", dependencies=[Depends(require_token)])
    def playback_start(req: PlaybackStartRequest) -> dict[str, Any]:
        with library_gate.use():
            return manager.start(req.prepare_token, data_dir=app.state.data_dir)

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
