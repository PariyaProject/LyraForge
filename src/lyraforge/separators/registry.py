"""Extensible registry of audio source separation providers."""

from __future__ import annotations

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.separators.base import AudioSeparator, SeparatorInfo
from lyraforge.separators.demucs import DemucsSeparator

_SEPARATORS: dict[str, AudioSeparator] = {}


def register_separator(separator: AudioSeparator) -> None:
    """Register or replace an audio source separator provider."""
    _SEPARATORS[separator.id] = separator


def list_separators() -> list[SeparatorInfo]:
    return [sep.probe() for sep in _SEPARATORS.values()]


def get_separator(separator_id: str) -> AudioSeparator:
    sep = _SEPARATORS.get(separator_id)
    if sep is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown audio separator: {separator_id!r}",
            {"available": sorted(_SEPARATORS)},
        )
    return sep


register_separator(DemucsSeparator())
