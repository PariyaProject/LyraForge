"""Tests for the user-initiated administrator relaunch helper."""

from __future__ import annotations

import sys

from lyraforge import elevation


def test_relaunch_elevated_is_noop_outside_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert elevation.relaunch_elevated() is False


def test_relaunch_elevated_uses_runas_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[tuple[str, str, str]] = []

    class _FakeShell32:
        @staticmethod
        def ShellExecuteW(_hwnd, verb, exe, params, _cwd, _show):  # noqa: N802 - Win32 name
            calls.append((str(verb), str(exe), str(params)))
            return 42

    class _FakeWindll:
        shell32 = _FakeShell32()

    monkeypatch.setattr(elevation, "ctypes", type("C", (), {"windll": _FakeWindll}), raising=False)
    # The module imports ctypes lazily; provide it via sys.modules for this call.
    import types

    fake_ctypes = types.SimpleNamespace(windll=_FakeWindll)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert elevation.relaunch_elevated() is True
    assert calls and calls[0][0] == "runas"
