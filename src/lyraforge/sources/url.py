"""User-authorized direct http(s) URL adapter with DNS-pinned anti-SSRF and budget guards."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_bytes, resolve_under
from lyraforge.media import MediaLimits
from lyraforge.sources.base import SourceCandidate
from lyraforge.sources.local import ALLOWED_SOURCE_EXTENSIONS, MIDI_EXTENSIONS, classify_extension

_FORBIDDEN_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _is_forbidden_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        isinstance(ip, ipaddress.IPv6Address)
        and ip.sixtofour is not None
        and _is_forbidden_ip(str(ip.sixtofour))
    ):
        return True
    return bool(
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_public_http_url(url: str) -> tuple[urllib.parse.ParseResult, str]:
    """Validate URL and resolve a pinned public IPv4/IPv6 address (prevents DNS rebinding)."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unsupported URL scheme {parsed.scheme!r}; only http(s) allowed",
        )
    if parsed.username or parsed.password:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            "credentials embedded in URL are forbidden",
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
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        try:
            infos = socket.getaddrinfo(
                host, parsed.port or default_port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE, f"cannot resolve host {host!r}: {exc}"
            ) from exc
        resolved_ips = sorted({str(info[4][0]) for info in infos if info[4]})
        if not resolved_ips or any(_is_forbidden_ip(ip) for ip in resolved_ips):
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                f"URL hostname {host!r} resolves to a non-public IP address",
            ) from None
        return parsed, resolved_ips[0]
    if _is_forbidden_ip(host):
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"refusing non-public IP literal {host!r}",
        )
    return parsed, host


def validate_public_http_url(url: str) -> urllib.parse.ParseResult:
    """Validate that ``url`` is an external public http(s) URL (anti-SSRF)."""
    parsed, _ = resolve_public_http_url(url)
    return parsed


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        pinned_ip: str,
        context: ssl.SSLContext | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(host, context=context, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        # Preserve original hostname for TLS SNI and certificate hostname verification
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        pinned_ip = getattr(req, "_lyraforge_pinned_ip", None)
        if not pinned_ip:
            _, pinned_ip = resolve_public_http_url(req.full_url)
        return self.do_open(
            lambda host, **kw: _PinnedHTTPConnection(host, pinned_ip=pinned_ip, **kw), req
        )


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        pinned_ip = getattr(req, "_lyraforge_pinned_ip", None)
        if not pinned_ip:
            _, pinned_ip = resolve_public_http_url(req.full_url)
        ctx = self._context or ssl.create_default_context()
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(
                host, pinned_ip=pinned_ip, context=ctx, **kw
            ),
            req,
        )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int = 5) -> None:
        super().__init__()
        self.max_redirects = max_redirects

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        count = int(getattr(req, "_lyraforge_redirects", 0)) + 1
        if count > self.max_redirects:
            raise LyraError(
                ErrorCode.LIMIT_EXCEEDED,
                f"URL redirect count exceeded max limit ({self.max_redirects})",
            )
        _, pinned_ip = resolve_public_http_url(newurl)
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            new_req._lyraforge_redirects = count  # type: ignore[attr-defined]
            new_req._lyraforge_pinned_ip = pinned_ip  # type: ignore[attr-defined]
        return new_req


class DirectUrlSourceAdapter:
    """Downloads user-supplied, user-authorized direct MIDI or audio URLs."""

    adapter_id = "direct-url"

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        timeout_s: float = 15.0,
        max_duration_s: float = 30.0,
        max_redirects: int = 5,
        opener: Any | None = None,
    ) -> None:
        self.max_bytes = max_bytes or MediaLimits().max_file_bytes
        self.timeout_s = timeout_s
        self.max_duration_s = max_duration_s
        self.max_redirects = max_redirects
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _PinnedHTTPHandler(),
            _PinnedHTTPSHandler(context=ssl.create_default_context()),
            _SafeRedirectHandler(max_redirects=max_redirects),
        )

    def search(self, query: str, *, limit: int = 10) -> list[SourceCandidate]:
        _ = limit
        q = query.strip()
        if not (q.startswith("http://") or q.startswith("https://")):
            return []
        parsed, _ = resolve_public_http_url(q)
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
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Path:
        if not user_authorized:
            raise LyraError(
                ErrorCode.PERMISSION_REQUIRED,
                "explicit user authorization (allow_network=True) required for external URLs",
            )
        if is_cancelled is not None and is_cancelled():
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "download cancelled")
        parsed, pinned_ip = resolve_public_http_url(location)
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
        req._lyraforge_pinned_ip = pinned_ip  # type: ignore[attr-defined]
        req._lyraforge_redirects = 0  # type: ignore[attr-defined]

        chunks: list[bytes] = []
        total = 0
        started = time.monotonic()
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                while True:
                    if is_cancelled is not None and is_cancelled():
                        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "download cancelled")
                    if time.monotonic() - started > self.max_duration_s:
                        raise LyraError(
                            ErrorCode.LIMIT_EXCEEDED,
                            f"URL download exceeded duration budget ({self.max_duration_s}s)",
                        )
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

        if is_cancelled is not None and is_cancelled():
            raise LyraError(ErrorCode.PLAYBACK_ABORTED, "download cancelled")
        target = resolve_under(dest_dir.resolve(), safe_name)
        atomic_write_bytes(target, b"".join(chunks))
        return target
