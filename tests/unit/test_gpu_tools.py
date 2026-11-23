"""Tests for dettato GPU detection, device preference and API surface."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.toolchain import gpu, runtime
from lyraforge.toolchain.paths import venv_python


@pytest.fixture()
def tools_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "tools"
    monkeypatch.setenv("LYRAFORGE_TOOLS_DIR", str(root))
    monkeypatch.delenv("LYRAFORGE_DETTATO_DEVICE", raising=False)
    return root


def test_detect_nvidia_parses_smi_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "C:/nvidia-smi.exe")
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *_a, **_kw: types.SimpleNamespace(
            returncode=0, stdout="NVIDIA GeForce RTX 4090, 551.23\n"
        ),
    )
    info = gpu.detect_nvidia()
    assert info == {"present": True, "name": "NVIDIA GeForce RTX 4090", "driver": "551.23"}


def test_detect_nvidia_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert gpu.detect_nvidia()["present"] is False


def test_probe_dettato_torch_reads_isolated_env(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = venv_python("dettato")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    payload = {"torch": "2.5.1+cu124", "cuda": "12.4", "available": True, "devices": 1}
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *_a, **_kw: types.SimpleNamespace(returncode=0, stdout=json.dumps(payload)),
    )
    probe = gpu.probe_dettato_torch()
    assert probe is not None
    assert probe["cuda_available"] is True
    assert probe["cuda_build"] == "12.4"


def test_device_preference_is_persisted_and_injected(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert gpu.device_setting() == "auto"

    gpu.set_device("cuda")
    assert gpu.device_setting() == "cuda"
    assert runtime.managed_env({"PATH": ""})["LYRAFORGE_DETTATO_DEVICE"] == "cuda"

    gpu.set_device("auto")
    assert "LYRAFORGE_DETTATO_DEVICE" not in runtime.managed_env({"PATH": ""})


def test_install_dettato_gpu_reinstalls_torch_from_cuda_index(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from lyraforge.toolchain import installer

    python = venv_python("dettato")
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(installer, "install_uv", lambda progress=None: Path("uv.exe"))
    monkeypatch.setattr(installer, "_run", fake_run)
    monkeypatch.setattr(
        gpu,
        "probe_dettato_torch",
        lambda: {"cuda_available": True, "version": "2.14.1+cu130"},
    )

    result = installer.install_dettato_gpu()
    assert result["installed"] is True
    cmd = calls[0]
    assert "--reinstall-package" in cmd and cmd[cmd.index("--reinstall-package") + 1] == "torch"
    assert cmd[cmd.index("--index-url") + 1].endswith("/cu130")


def test_gpu_api_status_device_and_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lyraforge.api import tool_service

    token = "gpu-token"
    app = create_app(data_dir=tmp_path / "gpu", session_token=token)
    client = TestClient(app)
    headers = {SESSION_TOKEN_HEADER: token}

    fake_status = {
        "nvidia": {"present": True, "name": "RTX 4090", "driver": "551.23"},
        "dettato_installed": True,
        "dettato_torch": {
            "version": "2.5.1",
            "cuda_build": "12.4",
            "cuda_available": True,
            "device_count": 1,
        },
        "device": "auto",
        "device_env": "LYRAFORGE_DETTATO_DEVICE",
    }
    monkeypatch.setattr("lyraforge.api.app.gpu_status", lambda: fake_status)
    monkeypatch.setattr(
        "lyraforge.api.app.set_dettato_device", lambda device: {**fake_status, "device": device}
    )
    monkeypatch.setattr(tool_service, "install_tool", lambda tool_id, progress=None: {"ok": True})

    status = client.get("/v1/gpu", headers=headers)
    assert status.status_code == 200
    assert status.json()["nvidia"]["name"] == "RTX 4090"

    changed = client.post("/v1/gpu/device", headers=headers, json={"device": "cuda"})
    assert changed.status_code == 200
    assert changed.json()["device"] == "cuda"

    installed = client.post("/v1/gpu/install", headers=headers)
    assert installed.status_code == 200
    assert installed.json()["install"]["tool_id"] == "dettato-gpu"
