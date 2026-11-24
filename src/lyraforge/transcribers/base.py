"""Pluggable audio->MIDI transcriber interfaces and option/result models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.playback.guards import StopToken

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    display_name: str
    available: bool
    license: str
    scope_note: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "available": self.available,
            "license": self.license,
            "scope_note": self.scope_note,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class TranscribeOptions:
    min_pitch: int = 36
    max_pitch: int = 96
    min_note_ms: int = 60
    onset_rms_threshold: float = 0.025
    timeout_s: float = 300.0
    onset_threshold: float | None = None
    frame_threshold: float | None = None
    min_frequency_hz: float | None = None
    max_frequency_hz: float | None = None

    def validate(self) -> None:
        if not (0 <= self.min_pitch < self.max_pitch <= 127):
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "min_pitch and max_pitch must satisfy 0 <= min_pitch < max_pitch <= 127",
            )
        if self.min_note_ms < 10:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_note_ms must be >= 10")
        if self.onset_rms_threshold <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "onset_rms_threshold must be > 0")
        if self.timeout_s <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "timeout_s must be > 0")
        if self.onset_threshold is not None and not (0.0 < self.onset_threshold < 1.0):
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "onset_threshold must be in (0, 1)")
        if self.frame_threshold is not None and not (0.0 < self.frame_threshold < 1.0):
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "frame_threshold must be in (0, 1)")
        if self.min_frequency_hz is not None and self.min_frequency_hz <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "min_frequency_hz must be > 0")
        if self.max_frequency_hz is not None and self.max_frequency_hz <= 0:
            raise LyraError(ErrorCode.INVALID_ARGUMENT, "max_frequency_hz must be > 0")
        if (
            self.min_frequency_hz is not None
            and self.max_frequency_hz is not None
            and self.max_frequency_hz <= self.min_frequency_hz
        ):
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "max_frequency_hz must be greater than min_frequency_hz",
            )


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    engine_id: str
    engine_version: str
    midi_bytes: bytes
    note_count: int
    duration_ms: int
    warnings: tuple[str, ...] = ()


@runtime_checkable
class Transcriber(Protocol):
    id: str

    def probe(self) -> ModelInfo: ...

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions | None = None,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> TranscriptionResult: ...
