"""Pluggable audio source separation interfaces and stem containers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lyraforge.playback.guards import StopToken

SeparatorProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class SeparatorInfo:
    id: str
    display_name: str
    available: bool
    license: str
    scope_note: str
    stems: tuple[str, ...] = ("vocals", "accompaniment")
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "available": self.available,
            "license": self.license,
            "scope_note": self.scope_note,
            "stems": list(self.stems),
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class SeparatedStems:
    vocals: Path | None = None
    accompaniment: Path | None = None
    bass: Path | None = None
    other: Path | None = None
    drums: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AudioSeparator(Protocol):
    id: str

    def probe(self) -> SeparatorInfo: ...

    def separate(
        self,
        wav_path: Path,
        out_dir: Path,
        *,
        on_progress: SeparatorProgressCallback | None = None,
        stop_token: StopToken | None = None,
    ) -> SeparatedStems: ...
