"""Pluggable transcription pipeline protocols and result/info data structures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lyraforge.music_core.models import NormalizedScore
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers.base import ProgressCallback, TranscribeOptions, Transcriber


@dataclass(frozen=True, slots=True)
class PipelineInfo:
    id: str
    display_name: str
    description: str
    recommended_for: str
    stages: tuple[str, ...]
    required_tools: tuple[str, ...]
    available: bool
    missing_tools: tuple[str, ...] = ()
    default_engine_id: str = "builtin-mono"
    default_vocal_engine_id: str | None = None
    default_accomp_engine_id: str | None = None
    default_arranger_strategy: str = "classic"
    supports_engine_override: bool = True
    resolved_vocal_engine_id: str | None = None
    resolved_accomp_engine_id: str | None = None
    low_resource_available: bool = False
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "recommended_for": self.recommended_for,
            "stages": list(self.stages),
            "required_tools": list(self.required_tools),
            "available": self.available,
            "missing_tools": list(self.missing_tools),
            "default_engine_id": self.default_engine_id,
            "default_vocal_engine_id": self.default_vocal_engine_id,
            "default_accomp_engine_id": self.default_accomp_engine_id,
            "default_arranger_strategy": self.default_arranger_strategy,
            "supports_engine_override": self.supports_engine_override,
            "resolved_vocal_engine_id": self.resolved_vocal_engine_id,
            "resolved_accomp_engine_id": self.resolved_accomp_engine_id,
            "low_resource_available": self.low_resource_available,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PipelineRequest:
    engine_id: str | None = None
    vocal_engine_id: str | None = None
    accomp_engine_id: str | None = None
    options: TranscribeOptions = field(default_factory=TranscribeOptions)
    transcriber_resolver: Callable[[str], Transcriber] | None = None
    vocal_cleanup: str = "standard"
    vocal_range: str = "auto"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    pipeline_id: str
    engine_id: str
    engine_version: str
    raw_midi_bytes: bytes
    cleaned_score: NormalizedScore
    cleaned_midi_bytes: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TranscriptionPipeline(Protocol):
    id: str

    def probe(self) -> PipelineInfo: ...

    def run(
        self,
        wav_path: Path,
        request: PipelineRequest,
        *,
        on_progress: ProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> PipelineResult: ...
