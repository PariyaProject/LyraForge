"""Unit tests for lyraforge.desktop.launcher."""

from __future__ import annotations

import importlib
import sys
import types
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from lyraforge.desktop import launcher
from lyraforge.errors import ErrorCode, LyraError


def test_pick_free_loopback_port() -> None:
    port = launcher.pick_free_loopback_port()
    assert 1024 <= port <= 65535


def test_launch_desktop_missing_pywebview_or_dist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_import = importlib.import_module

    def no_webview(name: str, package: str | None = None) -> Any:
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name, package)

    monkeypatch.setattr(launcher.importlib, "import_module", no_webview)
    with pytest.raises(LyraError) as exc:
        launcher.launch_desktop(data_dir=tmp_path)
    assert exc.value.code == ErrorCode.SOURCE_UNAVAILABLE

    fake_webview = types.SimpleNamespace(create_window=lambda *_a, **_kw: None, start=lambda: None)
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    with pytest.raises(LyraError) as exc2:
        launcher.launch_desktop(data_dir=tmp_path, static_dir=tmp_path / "missing_dist")
    assert exc2.value.code == ErrorCode.SOURCE_UNAVAILABLE

    with pytest.raises(LyraError) as exc3:
        launcher.launch_desktop(data_dir=tmp_path, dev_url="https://evil.example.com")
    assert exc3.value.code == ErrorCode.INVALID_ARGUMENT


def test_launch_desktop_happy_path_with_mocked_webview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body>OK</body></html>", encoding="utf-8")

    created: dict[str, Any] = {}
    started_called = False

    def fake_create_window(title: str, url: str, **kwargs: Any) -> None:
        created["title"] = title
        created["url"] = url
        created["kwargs"] = kwargs

    def fake_start() -> None:
        nonlocal started_called
        started_called = True
        with urllib.request.urlopen(f"{created['url']}health", timeout=2.0) as resp:  # noqa: S310
            assert resp.status == 200

    fake_webview = types.SimpleNamespace(create_window=fake_create_window, start=fake_start)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    rc = launcher.launch_desktop(data_dir=tmp_path / "data", static_dir=dist)
    assert rc == 0
    assert created["title"] == "LyraForge"
    assert created["url"].startswith("http://127.0.0.1:")
    assert started_called
