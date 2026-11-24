"""Regression tests ensuring Windows child subprocesses never flash console windows."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from lyraforge.media import subprocess_utils as su
from lyraforge.toolchain import gpu, installer
from lyraforge.toolchain.paths import venv_python
from lyraforge.transcribers import dettato


def _patch_windows_subprocess(
    monkeypatch: pytest.MonkeyPatch, *, windows: bool = True
) -> type[Any]:
    class _FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = -1

    monkeypatch.setattr(sys, "platform", "win32" if windows else "linux")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
    return _FakeStartupInfo


def test_hidden_subprocess_kwargs_posix_vs_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_windows_subprocess(monkeypatch, windows=False)
    assert su.hidden_subprocess_kwargs() == {}
    assert su.hidden_subprocess_kwargs(new_process_group=True) == {}

    fake_si_cls = _patch_windows_subprocess(monkeypatch, windows=True)
    kw = su.hidden_subprocess_kwargs()
    assert (kw["creationflags"] & 0x08000000) == 0x08000000
    assert (kw["creationflags"] & 0x00000200) == 0
    assert isinstance(kw["startupinfo"], fake_si_cls)
    assert kw["startupinfo"].dwFlags & 0x00000001
    assert kw["startupinfo"].wShowWindow == 0

    kw_grp = su.hidden_subprocess_kwargs(new_process_group=True)
    assert (kw_grp["creationflags"] & 0x08000000) == 0x08000000
    assert (kw_grp["creationflags"] & 0x00000200) == 0x00000200


def test_popen_isolation_and_kill_helpers_hide_windows_consoles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_si_cls = _patch_windows_subprocess(monkeypatch)

    popen_kw = su._popen_isolation_kwargs({"KEY": "VAL"})
    assert (popen_kw["creationflags"] & 0x08000000) == 0x08000000
    assert (popen_kw["creationflags"] & 0x00000200) == 0x00000200
    assert isinstance(popen_kw["startupinfo"], fake_si_cls)
    assert popen_kw["stdin"] is subprocess.DEVNULL
    assert popen_kw["env"]["KEY"] == "VAL"

    run_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        run_calls.append((list(cmd), dict(kwargs)))
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(su.subprocess, "run", fake_run)

    class _FakeProc:
        pid = 4321

        @staticmethod
        def poll() -> int:
            return 0

    su._terminate_process_tree(_FakeProc())
    assert [call[0][0] for call in run_calls] == ["taskkill", "powershell"]
    for _cmd, kwargs in run_calls:
        assert (kwargs["creationflags"] & 0x08000000) == 0x08000000
        assert isinstance(kwargs["startupinfo"], fake_si_cls)
        assert kwargs["stdin"] is subprocess.DEVNULL


def test_toolchain_and_dettato_probes_hide_windows_consoles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_si_cls = _patch_windows_subprocess(monkeypatch)
    monkeypatch.setenv("LYRAFORGE_TOOLS_DIR", str(tmp_path / "tools"))

    python = venv_python("dettato")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")

    observed: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> types.SimpleNamespace:
        observed.append((list(cmd), dict(kwargs)))
        first_arg = cmd[0]
        if first_arg == "C:/nvidia-smi.exe":
            return types.SimpleNamespace(returncode=0, stdout="RTX 4070, 560.70\n", stderr="")
        if "-c" in cmd and "devices" in cmd[-1]:
            return types.SimpleNamespace(
                returncode=0,
                stdout='{"torch": "2.4.1", "cuda": "12.4", "available": true, "devices": 1}',
                stderr="",
            )
        return types.SimpleNamespace(returncode=0, stdout="cuda\n", stderr="")

    monkeypatch.setattr("shutil.which", lambda _name: "C:/nvidia-smi.exe")
    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(dettato.subprocess, "run", fake_run)
    dettato._DEVICE_CACHE.clear()

    assert gpu.detect_nvidia()["present"] is True
    assert gpu.probe_dettato_torch()["cuda_available"] is True
    assert installer._run([sys.executable, "-V"]).returncode == 0
    assert dettato.resolve_device([str(python), "-m", "dettato"]) == "cuda"

    assert len(observed) == 4
    for _cmd, kwargs in observed:
        assert (kwargs["creationflags"] & 0x08000000) == 0x08000000
        assert isinstance(kwargs["startupinfo"], fake_si_cls)
        assert kwargs["stdin"] is subprocess.DEVNULL
