"""Pluggable audio source separation providers (Demucs, future RoFormer/MDX)."""

from __future__ import annotations

from lyraforge.separators.base import (
    AudioSeparator,
    SeparatedStems,
    SeparatorInfo,
    SeparatorProgressCallback,
)
from lyraforge.separators.demucs import DemucsSeparator
from lyraforge.separators.registry import (
    get_separator,
    list_separators,
    register_separator,
)

__all__ = [
    "AudioSeparator",
    "DemucsSeparator",
    "SeparatedStems",
    "SeparatorInfo",
    "SeparatorProgressCallback",
    "get_separator",
    "list_separators",
    "register_separator",
]
