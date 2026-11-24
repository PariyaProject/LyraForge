"""Tests for default and user-initiated Windows UAC administrator elevation."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from lyraforge import cli, elevation


def test_relaunch_elevated_is_noop_outside_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert elevation.relaunch_elevated() is False


def test_relaunch_elevated_uses_runas_and_prefers_pythonw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    py_exe = tmp_path / "python.exe"
    pyw_exe = tmp_path / "pythonw.exe"
    py_exe.write_text("", encoding="utf-8")
    pyw_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(py_exe))
    calls: list[tuple[str, str, str]] = []

    class _FakeShell32:
        @staticmethod
        def ShellExecuteW(_hwnd, verb, exe, params, _cwd, _show):  # noqa: N802 - Win32 name
            calls.append((str(verb), str(exe), str(params)))
            return 42

    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(shell32=_FakeShell32()))
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert elevation.relaunch_elevated(["--no-elevate"]) is True
    assert calls == [
        ("runas", str(pyw_exe), "-m lyraforge.cli desktop --no-elevate"),
    ]


def test_is_current_process_elevated_checks_win32_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert elevation.is_current_process_elevated() is False

    monkeypatch.setattr(sys, "platform", "win32")
    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            shell32=types.SimpleNamespace(IsUserAnAdmin=lambda: 1),
        )
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert elevation.is_current_process_elevated() is True

    fake_ctypes_std = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            shell32=types.SimpleNamespace(IsUserAnAdmin=lambda: 0),
        )
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes_std)
    assert elevation.is_current_process_elevated() is False


def test_maybe_elevate_for_desktop_guards_and_uac_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(elevation.NO_ELEVATE_ENV, raising=False)

    monkeypatch.setattr(sys, "platform", "darwin")
    assert elevation.maybe_elevate_for_desktop() is False

    monkeypatch.setattr(sys, "platform", "win32")
    assert elevation.maybe_elevate_for_desktop(disabled=True) is False

    monkeypatch.setenv(elevation.NO_ELEVATE_ENV, "1")
    assert elevation.maybe_elevate_for_desktop() is False
    monkeypatch.delenv(elevation.NO_ELEVATE_ENV, raising=False)

    monkeypatch.setattr(elevation, "is_current_process_elevated", lambda: True)
    assert elevation.maybe_elevate_for_desktop() is False

    monkeypatch.setattr(elevation, "is_current_process_elevated", lambda: False)
    seen_args: list[list[str]] = []
    monkeypatch.setattr(
        elevation,
        "relaunch_elevated",
        lambda extra_args=(): seen_args.append(list(extra_args)) or True,
    )
    assert elevation.maybe_elevate_for_desktop(["--data-dir", "C:/data"]) is True
    assert seen_args == [["--data-dir", "C:/data", "--no-elevate"]]

    # If the user cancels UAC prompt, fall back cleanly to non-elevated GUI launch.
    monkeypatch.setattr(elevation, "relaunch_elevated", lambda _extra=(): False)
    assert elevation.maybe_elevate_for_desktop() is False


def test_cmd_desktop_elevates_gui_but_not_self_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    elevate_calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        elevation,
        "maybe_elevate_for_desktop",
        lambda argv_args=(), *, disabled=False: elevate_calls.append(
            (list(argv_args), disabled)
        )
        or True,
    )

    assert (
        cli.main(["desktop", "--self-check", "--static-dir", str(dist)])
        == cli.EXIT_OK
    )
    assert elevate_calls == []

    launched: list[str] = []
    monkeypatch.setattr(
        "lyraforge.desktop.launch_desktop", lambda **_kw: launched.append("ok") or 0
    )
    assert cli.main(["desktop", "--data-dir", str(tmp_path / "lib")]) == cli.EXIT_OK
    assert elevate_calls == [(["--data-dir", str(tmp_path / "lib")], False)]
    assert launched == []

    # Opt-out passes disabled=True and continues into GUI launcher.
    monkeypatch.setattr(
        elevation,
        "maybe_elevate_for_desktop",
        lambda argv_args=(), *, disabled=False: elevate_calls.append(
            (list(argv_args), disabled)
        )
        or False,
    )
    assert cli.main(["desktop", "--no-elevate", "--static-dir", str(dist)]) == 0
    assert elevate_calls[-1] == (["--static-dir", str(dist)], True)
    assert launched == ["ok"]
