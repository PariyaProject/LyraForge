"""Legal open-catalog online music search and deterministic candidate ranking."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.sources.base import SourceCandidate
from lyraforge.sources.local import ALLOWED_SOURCE_EXTENSIONS, MIDI_EXTENSIONS
from lyraforge.sources.url import (
    DirectUrlSourceAdapter,
    _PinnedHTTPHandler,
    _PinnedHTTPSHandler,
    _SafeRedirectHandler,
    resolve_public_http_url,
)

_OPEN_LICENSE_MARKERS = (
    "creativecommons.org",
    "publicdomain",
    "/cc0",
    "pdm",
    "cc-by",
    "public domain",
    "mit",
    "gpl",
    "user-imported",
    "local",
)


def _is_open_license(text: str) -> bool:
    low = (text or "").lower()
    return any(tok in low for tok in _OPEN_LICENSE_MARKERS)


def _relevance_score(title: str, artist: str, query: str) -> tuple[int, float]:
    q = query.strip().lower()
    if not q:
        return (1, 1.0)
    t_low = title.lower()
    combined = f"{title} {artist}".lower()
    if t_low == q:
        return (3, 1.0)
    if q in t_low:
        return (2, len(q) / max(1, len(t_low)))
    tokens = [tok for tok in q.split() if tok]
    if not tokens:
        return (0, 0.0)
    hits = sum(1 for tok in tokens if tok in combined)
    return (1 if hits > 0 else 0, hits / len(tokens))


def rank_candidates(candidates: Sequence[SourceCandidate], query: str) -> list[SourceCandidate]:
    """Rank sources by trust tier, ready MIDI preference, license clarity, and title match."""

    def _sort_key(item: tuple[int, SourceCandidate]) -> tuple[Any, ...]:
        idx, c = item
        trust = 3 if c.source_type == "library" else 2 if c.source_type == "local_dir" else 1
        fmt_prio = 2 if c.format == "midi" else 1
        lic_prio = 1 if _is_open_license(c.license_note) else 0
        rel_tier, rel_frac = _relevance_score(c.title, c.artist, query)
        return (-trust, -fmt_prio, -rel_tier, -round(rel_frac, 4), -lic_prio, idx)

    return [c for _, c in sorted(enumerate(candidates), key=_sort_key)]


class OpenMusicCatalogSourceAdapter:
    """Searches open-licensed public catalogs (Internet Archive) without bypassing DRM."""

    adapter_id = "archive-org"

    def __init__(
        self,
        *,
        timeout_s: float = 12.0,
        max_items: int = 4,
        opener: Any | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.max_items = max_items
        self._opener = opener or urllib.request.build_opener(
            _PinnedHTTPHandler(),
            _PinnedHTTPSHandler(context=ssl.create_default_context()),
            _SafeRedirectHandler(max_redirects=5),
        )
        self._url_fetcher = DirectUrlSourceAdapter(timeout_s=timeout_s, opener=self._opener)

    def _fetch_json(self, url: str) -> dict[str, Any]:
        parsed, pinned_ip = resolve_public_http_url(url)
        _ = parsed
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "LyraForge/0.1 (Open-Catalog Search)",
                "Accept": "application/json",
            },
            method="GET",
        )
        req._lyraforge_pinned_ip = pinned_ip  # type: ignore[attr-defined]
        req._lyraforge_redirects = 0  # type: ignore[attr-defined]
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw_bytes = resp.read(2_000_001)
                if len(raw_bytes) > 2_000_000:
                    raise LyraError(
                        ErrorCode.LIMIT_EXCEEDED,
                        "online catalog JSON response exceeded 2 MB safety limit",
                    )
                data = json.loads(raw_bytes.decode("utf-8"))
        except LyraError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"online catalog lookup failed: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, "online catalog returned non-object JSON")
        return data

    def search(self, query: str, *, limit: int = 10) -> list[SourceCandidate]:
        clean_q = query.strip()
        if not clean_q:
            return []
        safe_expr = clean_q.replace('"', " ")
        search_q = f'({safe_expr}) AND mediatype:(audio OR data)'
        params = urllib.parse.urlencode([
            ("q", search_q),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "licenseurl"),
            ("rows", str(max(limit, self.max_items * 2))),
            ("page", "1"),
            ("output", "json"),
        ])
        search_url = f"https://archive.org/advancedsearch.php?{params}"
        payload = self._fetch_json(search_url)
        docs = (payload.get("response") or {}).get("docs") or []

        candidates: list[SourceCandidate] = []
        inspected = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            ident = str(doc.get("identifier") or "").strip()
            license_url = str(doc.get("licenseurl") or "").strip()
            if not ident or not _is_open_license(license_url):
                continue
            inspected += 1
            if inspected > self.max_items:
                break

            meta_url = f"https://archive.org/metadata/{urllib.parse.quote(ident)}/files"
            files_doc = self._fetch_json(meta_url)
            files_list = files_doc.get("result") or []
            title = str(doc.get("title") or ident).strip()
            artist = str(doc.get("creator") or "").strip()

            # Sort files so .mid/.midi precedes audio formats inside the same item
            valid_files: list[tuple[int, str, str]] = []
            for f in files_list:
                if not isinstance(f, dict):
                    continue
                fname = str(f.get("name") or "").strip()
                ext = Path(fname).suffix.lower()
                if ext not in ALLOWED_SOURCE_EXTENSIONS:
                    continue
                fmt = "midi" if ext in MIDI_EXTENSIONS else "audio"
                prio = 0 if fmt == "midi" else 1
                valid_files.append((prio, fname, fmt))
            valid_files.sort(key=lambda t: (t[0], t[1]))
            if not valid_files:
                continue

            _, best_name, best_fmt = valid_files[0]
            dl_url = (
                f"https://archive.org/download/{urllib.parse.quote(ident)}/"
                f"{urllib.parse.quote(best_name)}"
            )
            candidates.append(
                SourceCandidate(
                    source_type="archive.org",
                    id=f"{ident}/{best_name}",
                    title=title,
                    artist=artist,
                    format=best_fmt,
                    location=dl_url,
                    license_note=f"Open-licensed Internet Archive item ({license_url})",
                    requires_authorization=True,
                )
            )
        return rank_candidates(candidates, clean_q)[:limit]

    def fetch(
        self,
        location: str,
        dest_dir: Path,
        *,
        user_authorized: bool = False,
    ) -> Path:
        return self._url_fetcher.fetch(location, dest_dir, user_authorized=user_authorized)
