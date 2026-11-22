"""Local library and user folder source adapter."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes, resolve_under
from lyraforge.media import SUPPORTED_MEDIA_EXTENSIONS
from lyraforge.sources.base import SourceCandidate

if TYPE_CHECKING:
    from lyraforge.library.store import LibraryStore

MIDI_EXTENSIONS = frozenset({".mid", ".midi"})
ALLOWED_SOURCE_EXTENSIONS = MIDI_EXTENSIONS | SUPPORTED_MEDIA_EXTENSIONS


def classify_extension(ext: str) -> str:
    low = ext.lower()
    if low in MIDI_EXTENSIONS:
        return "midi"
    if low in SUPPORTED_MEDIA_EXTENSIONS:
        return "audio"
    raise LyraError(
        ErrorCode.MEDIA_UNSUPPORTED,
        f"unsupported source extension {ext!r}",
        {"allowed": sorted(ALLOWED_SOURCE_EXTENSIONS)},
    )


class LocalLibrarySourceAdapter:
    """Searches existing LibraryStore entries and optional user-owned folders."""

    adapter_id = "local"

    def __init__(
        self,
        store: LibraryStore | None = None,
        search_dirs: Sequence[str | Path] = (),
    ) -> None:
        self._store = store
        self._search_dirs = [Path(d).expanduser().resolve() for d in search_dirs]

    def search(self, query: str, *, limit: int = 10) -> list[SourceCandidate]:
        out: list[SourceCandidate] = []
        q_low = query.strip().lower()

        if self._store is not None:
            for song in self._store.search_songs(query)[:limit]:
                detail = self._store.get_song(song.id)
                fmt = "midi" if any(s.kind == "midi" for s in detail.sources) else "audio"
                out.append(
                    SourceCandidate(
                        source_type="library",
                        id=song.id,
                        title=song.title,
                        artist=song.artist,
                        format=fmt,
                        location=song.id,
                        license_note="Imported by user into local LyraForge library.",
                        requires_authorization=False,
                        license_id="user_local",
                        license_status="user_local",
                        rights_scope_note=(
                            "User-supplied local library asset; user retains copyright "
                            "responsibility."
                        ),
                    )
                )

        for root in self._search_dirs:
            if len(out) >= limit or not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
                if len(out) >= limit:
                    break
                if not path.is_file():
                    continue
                ext = path.suffix.lower()
                if ext not in ALLOWED_SOURCE_EXTENSIONS:
                    continue
                if q_low and q_low not in path.stem.lower():
                    continue
                # Ensure candidate cannot escape root via symlink
                rel = path.relative_to(root)
                resolved = resolve_under(root, rel)
                out.append(
                    SourceCandidate(
                        source_type="local_dir",
                        id=str(resolved),
                        title=path.stem,
                        artist="",
                        format="midi" if ext in MIDI_EXTENSIONS else "audio",
                        location=str(resolved),
                        license_note="User local file; confirm ownership/rights before sharing.",
                        requires_authorization=False,
                        license_id="user_local",
                        license_status="user_local",
                        rights_scope_note=(
                            "User local file; confirm work/recording/arrangement rights "
                            "before sharing."
                        ),
                    )
                )
        return out[:limit]

    def fetch(
        self,
        location: str,
        dest_dir: Path,
        *,
        user_authorized: bool = False,
    ) -> Path:
        _ = user_authorized
        src = Path(location).expanduser()
        if not src.is_file():
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"local source not found: {src.name}")
        ext = src.suffix.lower()
        classify_extension(ext)
        safe_name = f"{src.stem[:80]}{ext}"
        target = resolve_under(dest_dir.resolve(), safe_name)
        atomic_write_bytes(target, src.read_bytes())
        return target
