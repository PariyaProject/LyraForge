"""Thread-safe cancellable background job manager for audio transcription."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import LibraryStore
from lyraforge.pipelines import DEFAULT_PIPELINE_ID, get_pipeline
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers import TranscribeOptions, get_transcriber


@dataclass(slots=True)
class _TranscriptionJob:
    id: str
    song_id: str
    engine_id: str
    pipeline_id: str = DEFAULT_PIPELINE_ID
    status: str = "queued"  # queued | running | completed | cancelled | failed
    stage: str = "queued"
    progress: float = 0.0
    transcription: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    stop_token: StopToken = field(default_factory=StopToken)
    thread: threading.Thread | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def to_json(self) -> dict[str, Any]:
        now = self.finished_at if self.finished_at is not None else time.time()
        elapsed = max(0.0, now - self.started_at) if self.started_at is not None else 0.0
        return {
            "id": self.id,
            "song_id": self.song_id,
            "engine_id": self.engine_id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "transcription": self.transcription,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": round(elapsed, 1),
        }


class TranscriptionJobManager:
    """Runs bounded cancellable audio-to-MIDI jobs in background daemon threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _TranscriptionJob] = {}
        self._accepting = True
        self._pause_reason: str | None = None

    def pause_submissions(self, reason: str = "maintenance") -> None:
        with self._lock:
            self._accepting = False
            self._pause_reason = reason

    def resume_submissions(self) -> None:
        with self._lock:
            self._accepting = True
            self._pause_reason = None

    def active_job_ids(self) -> list[str]:
        with self._lock:
            return [
                j.id
                for j in self._jobs.values()
                if j.status in {"queued", "running"}
                or (j.thread is not None and j.thread.is_alive())
            ]

    def submit(
        self,
        song_id: str,
        *,
        engine_id: str,
        pipeline_id: str = DEFAULT_PIPELINE_ID,
        vocal_engine_id: str | None = None,
        accomp_engine_id: str | None = None,
        options: TranscribeOptions,
        data_dir: Path,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._accepting:
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY,
                    f"transcription submissions paused ({self._pause_reason or 'maintenance'})",
                )
        options.validate()
        pipeline = get_pipeline(pipeline_id)
        p_info = pipeline.probe()
        if not p_info.available:
            missing = ", ".join(p_info.missing_tools) or pipeline_id
            raise LyraError(
                ErrorCode.MODEL_MISSING,
                f"pipeline {pipeline_id!r} requires missing tool(s): {missing}",
            )
        if pipeline_id == DEFAULT_PIPELINE_ID:
            eng = get_transcriber(engine_id)
            info = eng.probe()
            if not info.available:
                raise LyraError(
                    ErrorCode.MODEL_MISSING,
                    f"transcriber {engine_id!r} is not installed on this machine",
                )
        else:
            for candidate_id in (vocal_engine_id, accomp_engine_id):
                if candidate_id and candidate_id != "auto":
                    eng = get_transcriber(candidate_id)
                    if not eng.probe().available:
                        raise LyraError(
                            ErrorCode.MODEL_MISSING,
                            f"transcriber {candidate_id!r} is not installed on this machine",
                        )

        with LibraryStore(data_dir) as store:
            detail = store.get_song(song_id)
            if not any(s.kind == "audio" for s in detail.sources):
                raise LyraError(
                    ErrorCode.SOURCE_UNAVAILABLE, f"song {song_id} has no audio/video source"
                )

        display_engine = (
            engine_id
            if pipeline_id == DEFAULT_PIPELINE_ID
            else p_info.default_engine_id
        )
        job = _TranscriptionJob(
            id=str(uuid.uuid4()),
            song_id=song_id,
            engine_id=display_engine,
            pipeline_id=pipeline_id,
        )

        def _on_progress(fraction: float, stage: str) -> None:
            with self._lock:
                if job.status in {"queued", "running"}:
                    job.progress = max(0.0, min(1.0, fraction))
                    job.stage = stage

        def _run() -> None:
            with self._lock:
                if job.stop_token.stopped:
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    return
                job.status = "running"
                job.stage = "extracting"
                job.started_at = time.time()
            try:
                with LibraryStore(data_dir) as store:
                    rec = store.transcribe_song(
                        song_id,
                        engine_id=engine_id,
                        pipeline_id=pipeline_id,
                        vocal_engine_id=vocal_engine_id,
                        accomp_engine_id=accomp_engine_id,
                        options=options,
                        on_progress=_on_progress,
                        stop_token=job.stop_token,
                    )
                with self._lock:
                    job.status = "completed"
                    job.stage = "completed"
                    job.progress = 1.0
                    job.finished_at = time.time()
                    job.engine_id = rec.engine
                    job.transcription = rec.to_json()
            except LyraError as exc:
                with self._lock:
                    job.finished_at = time.time()
                    if exc.code == ErrorCode.PLAYBACK_ABORTED or job.stop_token.stopped:
                        job.status = "cancelled"
                        job.stage = "cancelled"
                    else:
                        job.status = "failed"
                        job.stage = "failed"
                    job.error = exc.to_dict()
            except Exception as exc:  # pragma: no cover - defensive fallback
                with self._lock:
                    job.status = "failed"
                    job.stage = "failed"
                    job.finished_at = time.time()
                    job.error = {
                        "code": str(ErrorCode.TRANSCRIPTION_FAILED),
                        "message": f"{type(exc).__name__}: {exc}",
                        "details": {},
                    }

        thread = threading.Thread(
            target=_run,
            name=f"lyraforge-transcribe-{job.id[:8]}",
            daemon=True,
        )
        job.thread = thread
        with self._lock:
            if not self._accepting:
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY,
                    f"transcription submissions paused ({self._pause_reason or 'maintenance'})",
                )
            self._jobs[job.id] = job
            thread.start()
            return job.to_json()

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"job not found: {job_id}")
            return job.to_json()

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"job not found: {job_id}")
            job.stop_token.request_stop("user_cancelled")
            thread = job.thread
            if job.status == "queued":
                job.status = "cancelled"
                job.stage = "cancelled"
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        return self.get(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [j.to_json() for j in reversed(list(self._jobs.values()))]

    def cancel_all(
        self,
        reason: str = "shutdown",
        *,
        timeout_s: float = 5.0,
        pause_new: bool = False,
    ) -> list[str]:
        """Request cancellation for all background jobs and verify thread termination."""
        threads: list[threading.Thread] = []
        with self._lock:
            if pause_new:
                self._accepting = False
                self._pause_reason = reason
            for job in self._jobs.values():
                alive = job.thread is not None and job.thread.is_alive()
                if job.status in {"queued", "running"} or alive:
                    job.stop_token.request_stop(reason)
                    if job.status == "queued":
                        job.status = "cancelled"
                        job.stage = "cancelled"
                    if alive and job.thread is not None:
                        threads.append(job.thread)
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        for th in threads:
            rem = deadline - time.monotonic()
            if rem <= 0:
                break
            th.join(timeout=rem)
        return self.active_job_ids()
