"""Extensible transcription pipeline orchestration (direct, Demucs vocal/accomp split, etc.)."""

from __future__ import annotations

from lyraforge.pipelines.base import (
    PipelineInfo,
    PipelineRequest,
    PipelineResult,
    TranscriptionPipeline,
)
from lyraforge.pipelines.builtin import DirectPipeline, VocalSplitPipeline
from lyraforge.pipelines.registry import (
    DEFAULT_PIPELINE_ID,
    get_pipeline,
    list_pipelines,
    register_pipeline,
)

__all__ = [
    "DEFAULT_PIPELINE_ID",
    "DirectPipeline",
    "PipelineInfo",
    "PipelineRequest",
    "PipelineResult",
    "TranscriptionPipeline",
    "VocalSplitPipeline",
    "get_pipeline",
    "list_pipelines",
    "register_pipeline",
]
