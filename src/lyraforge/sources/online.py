"""Legal open-catalog online music search, strict license parsing, and candidate ranking."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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

_CC_VERSION_RE = re.compile(r"^\d+\.\d+$")
_EXACT_SPDX_ALLOWLIST: dict[str, tuple[str, str, bool]] = {
    "CC0-1.0": ("open_permissive", "https://creativecommons.org/publicdomain/zero/1.0/", True),
    "CC0": ("open_permissive", "https://creativecommons.org/publicdomain/zero/1.0/", True),
    "PDM-1.0": ("open_permissive", "https://creativecommons.org/publicdomain/mark/1.0/", True),
    "CC-BY-4.0": ("open_permissive", "https://creativecommons.org/licenses/by/4.0/", True),
    "CC-BY-3.0": ("open_permissive", "https://creativecommons.org/licenses/by/3.0/", True),
    "CC-BY-SA-4.0": ("open_permissive", "https://creativecommons.org/licenses/by-sa/4.0/", True),
    "CC-BY-SA-3.0": ("open_permissive", "https://creativecommons.org/licenses/by-sa/3.0/", True),
    "CC-BY-NC-4.0": ("open_restricted", "https://creativecommons.org/licenses/by-nc/4.0/", True),
    "CC-BY-NC-3.0": ("open_restricted", "https://creativecommons.org/licenses/by-nc/3.0/", True),
    "CC-BY-NC-SA-4.0": (
        "open_restricted",
        "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        True,
    ),
}
_DISTINCT_RIGHTS_SCOPE_NOTE = (
    "Underlying composition, sound recording, score arrangement, and MIDI encoding carry "
    "independent rights; catalog metadata from Internet Archive is self-reported and may be "
    "inaccurate—verify before commercial use or redistribution."
)


@dataclass(frozen=True, slots=True)
class LicenseClassification:
    """Auditable classification parsed strictly from a canonical license URL."""

    license_id: str
    status: str  # "open_permissive" | "open_restricted" | "unknown"
    normalized_url: str
    allow_derivative: bool
    note: str


def _unknown_license(raw: str, reason: str) -> LicenseClassification:
    return LicenseClassification(
        license_id="unknown",
        status="unknown",
        normalized_url="",
        allow_derivative=False,
        note=f"{reason} (raw={raw!r})" if raw else reason,
    )


def classify_license_url(raw_url: str) -> LicenseClassification:
    """Parse and validate a Creative Commons / Public Domain license URL strictly.

    Never relies on substring checks (`mit`, `gpl`, `local`, query params, or lookalike hosts).
    """
    text = (raw_url or "").strip()
    if not text:
        return _unknown_license("", "missing license URL")

    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return _unknown_license(text, "non-HTTP(S) license reference")
    if parsed.username or parsed.password or parsed.port is not None:
        return _unknown_license(text, "invalid authority in license URL")
    host = (parsed.hostname or "").lower()
    if host not in {"creativecommons.org", "www.creativecommons.org"}:
        return _unknown_license(text, f"unrecognized license authority {host!r}")

    parts = [p.lower() for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "publicdomain" and parts[1] == "zero" and parts[2] == "1.0":
        return LicenseClassification(
            license_id="CC0-1.0",
            status="open_permissive",
            normalized_url="https://creativecommons.org/publicdomain/zero/1.0/",
            allow_derivative=True,
            note="CC0 1.0 Universal Public Domain Dedication (metadata self-reported).",
        )
    if len(parts) >= 3 and parts[0] == "publicdomain" and parts[1] == "mark" and parts[2] == "1.0":
        return LicenseClassification(
            license_id="PDM-1.0",
            status="open_permissive",
            normalized_url="https://creativecommons.org/publicdomain/mark/1.0/",
            allow_derivative=True,
            note="Public Domain Mark 1.0 (metadata self-reported).",
        )

    if len(parts) >= 3 and parts[0] == "licenses" and _CC_VERSION_RE.match(parts[2]):
        code, ver = parts[1], parts[2]
        canonical = f"https://creativecommons.org/licenses/{code}/{ver}/"
        if code in {"by", "by-sa"}:
            return LicenseClassification(
                license_id=f"CC-{code.upper()}-{ver}",
                status="open_permissive",
                normalized_url=canonical,
                allow_derivative=True,
                note=f"Creative Commons {code.upper()} {ver} (allows adaptation with attribution).",
            )
        if code in {"by-nc", "by-nc-sa"}:
            return LicenseClassification(
                license_id=f"CC-{code.upper()}-{ver}",
                status="open_restricted",
                normalized_url=canonical,
                allow_derivative=True,
                note=f"Creative Commons {code.upper()} {ver} (non-commercial only).",
            )
        if code in {"by-nd", "by-nc-nd"}:
            return LicenseClassification(
                license_id=f"CC-{code.upper()}-{ver}",
                status="open_restricted",
                normalized_url=canonical,
                allow_derivative=False,
                note=(
                    f"Creative Commons {code.upper()} {ver} (NoDerivatives forbids "
                    "re-arrangement)."
                ),
            )

    return _unknown_license(text, "unrecognized Creative Commons license path")


def _classify_file_license(raw_value: str) -> LicenseClassification:
    val = (raw_value or "").strip()
    if val.lower().startswith(("http://", "https://")):
        return classify_license_url(val)
    upper = val.upper()
    if upper in _EXACT_SPDX_ALLOWLIST:
        status, norm_url, allow_deriv = _EXACT_SPDX_ALLOWLIST[upper]
        norm_id = "CC0-1.0" if upper == "CC0" else upper
        return LicenseClassification(
            license_id=norm_id,
            status=status,
            normalized_url=norm_url,
            allow_derivative=allow_deriv,
            note=f"File-level exact license token {norm_id}.",
        )
    return _unknown_license(val, "unverified file-level license declaration")


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


def _license_rank_tier(cand: SourceCandidate) -> int:
    if cand.source_type in {"library", "local_dir"} or cand.license_status == "user_local":
        return 3
    if cand.license_status == "open_permissive":
        return 2
    if cand.license_status == "open_restricted":
        return 1
    if cand.license_url:
        parsed = classify_license_url(cand.license_url)
        if parsed.allow_derivative:
            return 2 if parsed.status == "open_permissive" else 1
    return 0


def rank_candidates(candidates: Sequence[SourceCandidate], query: str) -> list[SourceCandidate]:
    """Rank sources by trust tier, normalized license clarity, MIDI readiness, and relevance."""

    def _sort_key(item: tuple[int, SourceCandidate]) -> tuple[Any, ...]:
        idx, c = item
        trust = 3 if c.source_type == "library" else 2 if c.source_type == "local_dir" else 1
        lic_prio = _license_rank_tier(c)
        fmt_prio = 2 if c.format == "midi" else 1
        rel_tier, rel_frac = _relevance_score(c.title, c.artist, query)
        return (-trust, -lic_prio, -fmt_prio, -rel_tier, -round(rel_frac, 4), idx)

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
            urllib.request.ProxyHandler({}),
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
        fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        candidates: list[SourceCandidate] = []
        inspected = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            ident = str(doc.get("identifier") or "").strip()
            license_url_raw = str(doc.get("licenseurl") or "").strip()
            lic_cls = classify_license_url(license_url_raw)
            if (
                not ident
                or lic_cls.status == "unknown"
                or not lic_cls.allow_derivative
            ):
                continue
            inspected += 1
            if inspected > self.max_items:
                break

            meta_url = f"https://archive.org/metadata/{urllib.parse.quote(ident)}/files"
            files_doc = self._fetch_json(meta_url)
            files_list = files_doc.get("result") or []
            if not isinstance(files_list, list):
                continue
            title = str(doc.get("title") or ident).strip()
            artist = str(doc.get("creator") or "").strip()

            valid_files: list[tuple[int, str, str, LicenseClassification]] = []
            for f in files_list:
                if not isinstance(f, dict):
                    continue
                if str(f.get("private") or "").strip().lower() in {"1", "true", "yes"}:
                    continue
                file_lic_raw = str(f.get("license") or "").strip()
                effective_lic = lic_cls
                if file_lic_raw:
                    file_cls = _classify_file_license(file_lic_raw)
                    if file_cls.status == "unknown" or not file_cls.allow_derivative:
                        continue
                    effective_lic = file_cls
                fname = str(f.get("name") or "").strip()
                ext = Path(fname).suffix.lower()
                if ext not in ALLOWED_SOURCE_EXTENSIONS:
                    continue
                fmt = "midi" if ext in MIDI_EXTENSIONS else "audio"
                prio = 0 if fmt == "midi" else 1
                valid_files.append((prio, fname, fmt, effective_lic))
            valid_files.sort(key=lambda t: (t[0], t[1]))
            if not valid_files:
                continue

            _, best_name, best_fmt, best_lic = valid_files[0]
            dl_url = (
                f"https://archive.org/download/{urllib.parse.quote(ident)}/"
                f"{urllib.parse.quote(best_name)}"
            )
            item_url = f"https://archive.org/details/{urllib.parse.quote(ident)}"
            candidates.append(
                SourceCandidate(
                    source_type="archive.org",
                    id=f"{ident}/{best_name}",
                    title=title,
                    artist=artist,
                    format=best_fmt,
                    location=dl_url,
                    license_note=f"Internet Archive metadata: {best_lic.license_id}",
                    requires_authorization=True,
                    license_id=best_lic.license_id,
                    license_status=best_lic.status,
                    license_url=best_lic.normalized_url,
                    source_url=item_url,
                    fetched_at=fetched_at,
                    rights_scope_note=_DISTINCT_RIGHTS_SCOPE_NOTE,
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
