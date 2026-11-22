"""Pluggable audio-to-MIDI transcription adapters (ADR-0001)."""

from lyraforge.transcribers.base import (
    ModelInfo,
    ProgressCallback,
    TranscribeOptions,
    Transcriber,
    TranscriptionResult,
)
from lyraforge.transcribers.basic_pitch import (
    BASIC_PITCH_CLI_ENV,
    BASIC_PITCH_PYTHON_ENV,
    BasicPitchSubprocessTranscriber,
)
from lyraforge.transcribers.builtin_mono import BuiltinMonoTranscriber
from lyraforge.transcribers.dettato import (
    DETTATO_CLI_ENV,
    DETTATO_PYTHON_ENV,
    DettatoSubprocessTranscriber,
)
from lyraforge.transcribers.registry import (
    DEFAULT_TRANSCRIBER_ID,
    get_transcriber,
    list_transcribers,
)

__all__ = [
    "BASIC_PITCH_CLI_ENV",
    "BASIC_PITCH_PYTHON_ENV",
    "BasicPitchSubprocessTranscriber",
    "BuiltinMonoTranscriber",
    "DEFAULT_TRANSCRIBER_ID",
    "DETTATO_CLI_ENV",
    "DETTATO_PYTHON_ENV",
    "DettatoSubprocessTranscriber",
    "ModelInfo",
    "ProgressCallback",
    "TranscribeOptions",
    "Transcriber",
    "TranscriptionResult",
    "get_transcriber",
    "list_transcribers",
]
