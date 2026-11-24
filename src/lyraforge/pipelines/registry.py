"""Extensible registry of transcription pipelines."""

from __future__ import annotations

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.pipelines.base import PipelineInfo, TranscriptionPipeline
from lyraforge.pipelines.builtin import DirectPipeline, VocalSplitPipeline

DEFAULT_PIPELINE_ID = "direct"

_PIPELINES: dict[str, TranscriptionPipeline] = {}


def register_pipeline(pipeline: TranscriptionPipeline) -> None:
    """Register or replace a transcription pipeline implementation."""
    _PIPELINES[pipeline.id] = pipeline


def list_pipelines() -> list[PipelineInfo]:
    return [p.probe() for p in _PIPELINES.values()]


def get_pipeline(pipeline_id: str = DEFAULT_PIPELINE_ID) -> TranscriptionPipeline:
    pipeline = _PIPELINES.get(pipeline_id)
    if pipeline is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown transcription pipeline: {pipeline_id!r}",
            {"available": sorted(_PIPELINES)},
        )
    return pipeline


register_pipeline(DirectPipeline())
register_pipeline(VocalSplitPipeline("full"))
register_pipeline(VocalSplitPipeline("lead"))
register_pipeline(VocalSplitPipeline("accomp"))
