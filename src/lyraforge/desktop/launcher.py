"""Dual-OS PyWebView desktop host (macOS WKWebView/Cocoa & Windows WebView2).

Starts the local 127.0.0.1 FastAPI server on an ephemeral port with a fresh
per-launch session token, opens a PyWebView window, and guarantees clean
playback stop + server shutdown when the window closes.
"""

from __future__ import annotations

import importlib
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import uvicorn

from lyraforge.api import create_app
from lyraforge.api.app import default_web_dist_dir
from lyraforge.errors import ErrorCode, LyraError


def pick_free_loopback_port() -> int:
    """Bind an ephemeral loopback port and release it for uvicorn."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, *, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    health_url = f"{base_url}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as resp:  # noqa: S310
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)
    raise LyraError(
        ErrorCode.SOURCE_UNAVAILABLE,
        f"local API server did not become healthy within {timeout_s:.1f}s",
    )


def _import_webview() -> Any:
    try:
        return importlib.import_module("webview")
    except ModuleNotFoundError as exc:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "pywebview is not installed; install desktop extra with 'uv sync --extra desktop'",
        ) from exc


def launch_desktop(
    *,
    data_dir: str | Path | None = None,
    static_dir: str | Path | None = None,
    dev_url: str | None = None,
    width: int = 1180,
    height: int = 780,
) -> int:
    """Launch the PyWebView desktop window backed by the local FastAPI server."""
    webview = _import_webview()

    resolved_static: Path | None = None
    cors_origins: tuple[str, ...] = ()
    if dev_url:
        parsed = urlparse(dev_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                "dev_url must point to http(s)://127.0.0.1 or localhost",
                {"dev_url": dev_url},
            )
        cors_origins = (f"{parsed.scheme}://{parsed.netloc}",)
    else:
        resolved_static = (
            Path(static_dir).expanduser().resolve()
            if static_dir is not None
            else default_web_dist_dir()
        )
        if resolved_static is None or not (resolved_static / "index.html").is_file():
            raise LyraError(
                ErrorCode.SOURCE_UNAVAILABLE,
                "built desktop web UI not found; run 'pnpm --dir apps/desktop/web build'",
            )

    port = pick_free_loopback_port()
    token = secrets.token_urlsafe(32)
    app = create_app(
        data_dir=data_dir,
        session_token=token,
        cors_origins=cors_origins,
        static_dir=resolved_static,
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="lyraforge-api-server", daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url)
        if dev_url:
            frag = urlencode({"apiBase": base_url, "sessionToken": token})
            target_url = f"{dev_url.rstrip('/')}#{frag}"
        else:
            target_url = f"{base_url}/"
        webview.create_window(
            "LyraForge",
            target_url,
            width=width,
            height=height,
            min_size=(900, 640),
        )
        webview.start()
        return 0
    finally:
        app.state.playback_manager.stop("window_closed")
        server.should_exit = True
        thread.join(timeout=3.0)
