"""Thread-safe cancellable background job manager for audio transcription."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import LibraryStore
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers import TranscribeOptions, get_transcriber


@dataclass(slots=True)
class _TranscriptionJob:
    id: str
    song_id: str
    engine_id: str
    status: str = "queued"  # queued | running | completed | cancelled | failed
    stage: str = "queued"
    progress: float = 0.0
    transcription: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    stop_token: StopToken = field(default_factory=StopToken)
    thread: threading.Thread | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "song_id": self.song_id,
            "engine_id": self.engine_id,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "transcription": self.transcription,
            "error": self.error,
        }


class TranscriptionJobManager:
    """Runs bounded cancellable audio-to-MIDI jobs in background daemon threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _TranscriptionJob] = {}

    def submit(
        self,
        song_id: str,
        *,
        engine_id: str,
        options: TranscribeOptions,
        data_dir: Path,
    ) -> dict[str, Any]:
        options.validate()
        eng = get_transcriber(engine_id)
        info = eng.probe()
        if not info.available:
            raise LyraError(
                ErrorCode.MODEL_MISSING,
                f"transcriber {engine_id!r} is not installed on this machine",
            )
        with LibraryStore(data_dir) as store:
            detail = store.get_song(song_id)
            if not any(s.kind == "audio" for s in detail.sources):
                raise LyraError(
                    ErrorCode.SOURCE_UNAVAILABLE, f"song {song_id} has no audio/video source"
                )

        job = _TranscriptionJob(id=str(uuid.uuid4()), song_id=song_id, engine_id=engine_id)

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
            try:
                with LibraryStore(data_dir) as store:
                    rec = store.transcribe_song(
                        song_id,
                        engine_id=engine_id,
                        options=options,
                        on_progress=_on_progress,
                        stop_token=job.stop_token,
                    )
                with self._lock:
                    job.status = "completed"
                    job.stage = "completed"
                    job.progress = 1.0
                    job.transcription = rec.to_json()
            except LyraError as exc:
                with self._lock:
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
            self._jobs[job.id] = job
        thread.start()
        with self._lock:
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
