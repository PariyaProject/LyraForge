"""Transcriber registry."""

from __future__ import annotations

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.transcribers.base import ModelInfo, Transcriber
from lyraforge.transcribers.basic_pitch import BasicPitchSubprocessTranscriber
from lyraforge.transcribers.builtin_mono import BuiltinMonoTranscriber
from lyraforge.transcribers.dettato import DettatoSubprocessTranscriber

DEFAULT_TRANSCRIBER_ID = "builtin-mono"


def _engines() -> dict[str, Transcriber]:
    items: list[Transcriber] = [
        BuiltinMonoTranscriber(),
        BasicPitchSubprocessTranscriber(),
        DettatoSubprocessTranscriber(),
    ]
    return {t.id: t for t in items}


def list_transcribers() -> list[ModelInfo]:
    return [t.probe() for t in _engines().values()]


def get_transcriber(engine_id: str = DEFAULT_TRANSCRIBER_ID) -> Transcriber:
    engines = _engines()
    eng = engines.get(engine_id)
    if eng is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown transcriber engine: {engine_id!r}",
            {"available": sorted(engines)},
        )
    return eng
