"""Source adapters for local library, user folders, and authorized direct URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    source_type: str  # "library" | "local_dir" | "url" | "archive.org"
    id: str
    title: str
    artist: str
    format: str  # "midi" | "audio"
    location: str
    license_note: str
    requires_authorization: bool = False
    license_id: str = "unknown"
    # "user_local" | "open_permissive" | "open_restricted" | "unknown"
    license_status: str = "unknown"
    license_url: str = ""
    source_url: str = ""
    fetched_at: str = ""
    rights_scope_note: str = ""

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
            "license_id": self.license_id,
            "license_status": self.license_status,
            "license_url": self.license_url,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "rights_scope_note": self.rights_scope_note,
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
