"""Source adapters for local library, user folders, and authorized direct URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    source_type: str  # "library" | "local_dir" | "url"
    id: str
    title: str
    artist: str
    format: str  # "midi" | "audio"
    location: str
    license_note: str
    requires_authorization: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "format": self.format,
            "location": self.location,
            "license_note": self.license_note,
            "requires_authorization": self.requires_authorization,
        }


class SourceAdapter(Protocol):
    adapter_id: str

    def search(self, query: str, *, limit: int = 10) -> list[SourceCandidate]:
        ...

    def fetch(
        self,
        location: str,
        dest_dir: Path,
        *,
        user_authorized: bool = False,
    ) -> Path:
        ...
