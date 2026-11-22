"""User-authorized direct http(s) URL adapter with strict SSRF and size guards."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes, resolve_under
from lyraforge.media import MediaLimits
from lyraforge.sources.base import SourceCandidate
from lyraforge.sources.local import ALLOWED_SOURCE_EXTENSIONS, MIDI_EXTENSIONS, classify_extension

_FORBIDDEN_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def _is_forbidden_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(url: str) -> urllib.parse.ParseResult:
    """Validate that ``url`` is an external public http(s) URL (anti-SSRF)."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported URL scheme {parsed.scheme!r}; only http(s) allowed",
        )
    host = (parsed.hostname or "").strip().lower()
    if not host or host in _FORBIDDEN_HOSTNAMES or host.endswith((".local", ".internal")):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"refusing loopback or local URL hostname {host!r}",
        )
    try:
        ipaddress.ip_address(host)
    except ValueError:
        default_port = 443 if parsed.scheme == "https" else 80
        try:
            infos = socket.getaddrinfo(host, parsed.port or default_port)
        except socket.gaierror as exc:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"cannot resolve host {host!r}: {exc}"
            ) from exc
        resolved_ips = {info[4][0] for info in infos if info[4]}
        if not resolved_ips or any(_is_forbidden_ip(ip) for ip in resolved_ips):
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                f"URL hostname {host!r} resolves to a non-public IP address",
            ) from None
    else:
        if _is_forbidden_ip(host):
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                f"refusing non-public IP literal {host!r}",
            )
    return parsed


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DirectUrlSourceAdapter:
    """Downloads user-supplied, user-authorized direct MIDI or audio URLs."""

    adapter_id = "direct-url"

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        timeout_s: float = 15.0,
        opener: Any | None = None,
    ) -> None:
        self.max_bytes = max_bytes or MediaLimits().max_file_bytes
        self.timeout_s = timeout_s
        self._opener = opener or urllib.request.build_opener(_SafeRedirectHandler())

    def search(self, query: str, *, limit: int = 10) -> list[SourceCandidate]:
        _ = limit
        q = query.strip()
        if not (q.startswith("http://") or q.startswith("https://")):
            return []
        parsed = validate_public_http_url(q)
        name = Path(parsed.path).name or "remote_source.mid"
        ext = Path(name).suffix.lower() or ".mid"
        fmt = "midi" if ext in MIDI_EXTENSIONS else "audio"
        if ext not in ALLOWED_SOURCE_EXTENSIONS:
            classify_extension(ext)
        return [
            SourceCandidate(
                source_type="url",
                id=q,
                title=Path(name).stem or "remote_source",
                artist="external",
                format=fmt,
                location=q,
                license_note=(
                    "User-provided external URL; confirm source license/rights before sharing."
                ),
                requires_authorization=True,
            )
        ]

    def fetch(
        self,
        location: str,
        dest_dir: Path,
        *,
        user_authorized: bool = False,
    ) -> Path:
        if not user_authorized:
            raise LyraError(
                ErrorCode.PERMISSION_REQUIRED,
                "explicit user authorization (allow_network=True) required for external URLs",
            )
        parsed = validate_public_http_url(location)
        raw_name = Path(parsed.path).name or "download.mid"
        ext = Path(raw_name).suffix.lower()
        if not ext:
            ext = ".mid"
        classify_extension(ext)
        raw_stem = Path(raw_name).stem
        safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw_stem)
        safe_name = f"{safe_stem[:64] or 'download'}{ext}"

        req = urllib.request.Request(
            location,
            headers={"User-Agent": "LyraForge/0.1 (User-Authorized Fetch)"},
            method="GET",
        )
        chunks: list[bytes] = []
        total = 0
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                while True:
                    block = resp.read(65_536)
                    if not block:
                        break
                    total += len(block)
                    if total > self.max_bytes:
                        raise LyraError(
                            ErrorCode.LIMIT_EXCEEDED,
                            f"downloaded source exceeds max size ({self.max_bytes} bytes)",
                        )
                    chunks.append(block)
        except LyraError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"failed to download URL: {exc}"
            ) from exc

        target = resolve_under(dest_dir.resolve(), safe_name)
        atomic_write_bytes(target, b"".join(chunks))
        return target
