"""Regression tests for silent desktop-startup failures.

The Windows pre-release shipped a PyInstaller bundle without pywebview: the EXE had no
console, imported the GUI host through ``importlib``, failed within a second and showed
nothing at all. These tests pin the diagnostics (log + native dialog), the CLI error
reporter hook and the ``--check-gui`` release gate.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from lyraforge import cli, startup_report
from lyraforge.errors import ErrorCode, LyraError


def test_startup_log_path_is_per_user_and_platform_specific(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    assert (
        startup_report.startup_log_path()
        == tmp_path / "localappdata" / "LyraForge" / "logs" / "startup.log"
    )

    monkeypatch.setattr(sys, "platform", "darwin")
    assert startup_report.startup_log_path().parts[-4:] == (
        "Library",
        "Logs",
        "LyraForge",
        "startup.log",
    )

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert startup_report.startup_log_path() == (
        tmp_path / "state" / "lyraforge" / "logs" / "startup.log"
    )


def test_write_startup_log_rotates_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(startup_report, "startup_log_path", lambda: log_dir / "startup.log")

    written = startup_report.write_startup_log("first failure")
    assert written is not None
    assert written.read_text(encoding="utf-8").endswith("first failure\n")

    (log_dir / "startup.log").write_bytes(b"x" * (startup_report._MAX_LOG_BYTES + 1))
    startup_report.write_startup_log("second failure")
    assert (log_dir / "startup.log.1").is_file()
    assert "second failure" in (log_dir / "startup.log").read_text(encoding="utf-8")

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(startup_report, "startup_log_path", lambda: blocker / "startup.log")
    assert startup_report.write_startup_log("cannot be written") is None


def test_report_startup_failure_logs_traceback_and_shows_dialog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "startup.log"
    monkeypatch.setattr(startup_report, "startup_log_path", lambda: log_path)
    shown: list[tuple[str, str]] = []

    def fake_dialog(title: str, message: str) -> bool:
        shown.append((title, message))
        return True

    monkeypatch.setattr(startup_report, "show_error_dialog", fake_dialog)
    error = LyraError(ErrorCode.SOURCE_UNAVAILABLE, "pywebview is not installed")

    returned = startup_report.report_startup_failure(error, argv=["LyraForge.exe"])

    assert returned == log_path
    logged = log_path.read_text(encoding="utf-8")
    assert "[SOURCE_UNAVAILABLE] pywebview is not installed" in logged
    assert "command: LyraForge.exe" in logged
    assert "Traceback" in logged or "LyraError" in logged
    assert shown, "a native dialog must be shown for a fatal startup failure"
    title, message = shown[0]
    assert "could not start" in title
    assert "pywebview is not installed" in message
    assert str(log_path) in message


def test_report_startup_failure_handles_unexpected_exceptions_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(startup_report, "startup_log_path", lambda: tmp_path / "startup.log")
    monkeypatch.setattr(startup_report, "show_error_dialog", lambda _t, _m: True)

    startup_report.report_startup_failure(ValueError("boom"), argv=[])

    logged = (tmp_path / "startup.log").read_text(encoding="utf-8")
    assert "ValueError: boom" in logged
    assert "command: <unknown>" in logged


def test_cli_main_invokes_error_reporter_for_domain_errors(tmp_path: Path) -> None:
    seen: list[LyraError] = []

    code = cli.main(["validate", str(tmp_path / "missing.json")], error_reporter=seen.append)

    assert code == cli.EXIT_ERROR
    assert len(seen) == 1
    assert seen[0].code == ErrorCode.SOURCE_UNAVAILABLE


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body>OK</body></html>", encoding="utf-8")
    return dist


def test_self_check_gui_gate_rejects_missing_pywebview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_import = importlib.import_module

    def no_webview(name: str, package: str | None = None) -> Any:
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", no_webview)
    seen: list[LyraError] = []

    code = cli.main(
        ["desktop", "--self-check", "--check-gui", "--static-dir", str(_make_dist(tmp_path))],
        error_reporter=seen.append,
    )

    assert code == cli.EXIT_ERROR
    assert len(seen) == 1
    assert "pywebview" in seen[0].message


def test_frozen_bundle_self_check_requires_gui_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_import = importlib.import_module

    def no_webview(name: str, package: str | None = None) -> Any:
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", no_webview)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    seen: list[LyraError] = []

    code = cli.main(
        ["desktop", "--self-check", "--static-dir", str(_make_dist(tmp_path))],
        error_reporter=seen.append,
    )

    assert code == cli.EXIT_ERROR
    assert len(seen) == 1
    assert "pywebview" in seen[0].message


def test_check_gui_accepts_importable_webview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(__version__="6.2.1"))

    code = cli.main(
        ["desktop", "--self-check", "--check-gui", "--static-dir", str(_make_dist(tmp_path))]
    )

    assert code == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["gui_host"]["available"] is True
    assert payload["gui_host"]["version"] == "6.2.1"


def test_check_gui_reports_version_without_dunder_attribute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))
    monkeypatch.setitem(
        sys.modules, "webview._version", types.SimpleNamespace(__version__="6.2.1")
    )

    code = cli.main(
        ["desktop", "--self-check", "--check-gui", "--static-dir", str(_make_dist(tmp_path))]
    )

    assert code == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["gui_host"]["version"] == "6.2.1"


def test_windows_backend_failure_is_fatal_only_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(__version__="6.2.1"))
    real_import = importlib.import_module

    def broken_backend(name: str, package: str | None = None) -> Any:
        if name == "webview.platforms.edgechromium":
            raise ImportError("pythonnet runtime missing")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", broken_backend)

    with pytest.raises(LyraError) as exc:
        cli._gui_host_status(required=True)
    assert exc.value.code == ErrorCode.SOURCE_UNAVAILABLE
    assert "WebView2" in exc.value.message

    status = cli._gui_host_status(required=False)
    assert status["backend_ok"] is False
    assert "pythonnet runtime missing" in status["reason"]
