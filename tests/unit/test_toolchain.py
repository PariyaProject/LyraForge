"""Unit tests for lyraforge.toolchain (download-on-demand installer, no real network)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import types
import zipfile
from pathlib import Path
from typing import Any

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.toolchain import installer, runtime
from lyraforge.toolchain.paths import (
    ffmpeg_executable,
    manifest_file,
    tools_dir,
    uv_executable,
    venv_python,
)


def _write_manifest(tools: dict[str, Any]) -> None:
    path = manifest_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "tools": tools}), encoding="utf-8")


def _make_wheel(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _wheel_entry(filename: str) -> dict[str, str]:
    return {
        "filename": filename,
        "url": "https://files.pythonhosted.org/x.whl",
        "digests": {"sha256": "0" * 64},
    }


def _fake_run_factory(
    *,
    stdout: str = "ffmpeg version 9.0.2 Copyright (c) test\n",
    returncode: int = 0,
    on_venv: Path | None = None,
) -> Any:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> types.SimpleNamespace:
        calls.append(list(cmd))
        if on_venv is not None and "venv" in cmd:
            python = on_venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    fake_run.calls = calls  # type: ignore[attr-defined]
    return fake_run


@pytest.fixture()
def tools_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "tools"
    monkeypatch.setenv("LYRAFORGE_TOOLS_DIR", str(root))
    monkeypatch.delenv("LYRAFORGE_FFMPEG_BIN", raising=False)
    monkeypatch.delenv("LYRAFORGE_BASIC_PITCH_PYTHON", raising=False)
    monkeypatch.delenv("LYRAFORGE_DETTATO_PYTHON", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    return root


def test_status_without_tools_reports_all_missing(tools_root: Path) -> None:
    status = {item["id"]: item for item in installer.status()}
    assert set(status) == {"ffmpeg", "basic-pitch", "dettato"}
    assert all(item["installed"] is False for item in status.values())
    assert tools_dir() == tools_root


def test_platform_tags_follow_os_and_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    assert installer._platform_tags() == ("win_amd64",)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert "macosx_11_0_arm64" in installer._platform_tags()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert installer._platform_tags()[0].startswith("manylinux")


def test_pick_wheel_matches_platform_and_rejects_unknown() -> None:
    files = [
        {"filename": "pkg-1.0-cp311-cp311-manylinux_2_17_x86_64.whl"},
        {"filename": "pkg-1.0-py3-none-win_amd64.whl"},
    ]
    assert installer._pick_wheel(files, ("win_amd64",))["filename"].endswith("win_amd64.whl")
    with pytest.raises(LyraError) as exc:
        installer._pick_wheel(files, ("macosx_11_0_arm64",))
    assert exc.value.code == ErrorCode.MODEL_MISSING


def test_download_verifies_sha256_and_rejects_foreign_hosts(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"wheel-bytes"

    class FakeResponse:
        def __init__(self) -> None:
            self._sent = False

        def read(self, _n: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return payload

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_kw: FakeResponse())
    digest = hashlib.sha256(payload).hexdigest()
    dest = tools_root / "a.bin"
    installer._download("https://files.pythonhosted.org/x.whl", dest, expected_sha256=digest)
    assert dest.read_bytes() == payload

    with pytest.raises(LyraError) as exc_bad_sha:
        installer._download("https://files.pythonhosted.org/y.whl", dest, expected_sha256="0" * 64)
    assert exc_bad_sha.value.code == ErrorCode.PACKAGE_INVALID
    assert not dest.exists()

    with pytest.raises(LyraError) as exc_host:
        installer._download("https://evil.example.com/x.whl", dest, expected_sha256=digest)
    assert exc_host.value.code == ErrorCode.SOURCE_UNAVAILABLE


def test_install_ffmpeg_extracts_binary_and_records_manifest(
    tools_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _make_wheel(
        tmp_path / "imageio.whl",
        {"imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v9.0.2.exe": b"MZ-fake-ffmpeg"},
    )
    monkeypatch.setattr(installer, "_platform_tags", lambda: ("win_amd64",))
    monkeypatch.setattr(
        installer,
        "_pypi_release",
        lambda *_a, **_kw: [_wheel_entry("imageio_ffmpeg-0.8.1-py3-none-win_amd64.whl")],
    )

    def fake_download(_url: str, dest: Path, **_kw: Any) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel.read_bytes())

    monkeypatch.setattr(installer, "_download", fake_download)
    monkeypatch.setattr(installer, "_run", _fake_run_factory())

    target = installer.install_ffmpeg()
    assert target == ffmpeg_executable()
    assert target.read_bytes().startswith(b"MZ-fake-ffmpeg")
    manifest = json.loads(manifest_file().read_text(encoding="utf-8"))
    assert manifest["tools"]["ffmpeg"]["version"] == "9.0.2"
    assert {item["id"]: item for item in installer.status()}["ffmpeg"]["installed"] is True


def test_install_uv_extracts_scripts_member(
    tools_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe_name = "uv.exe" if sys.platform == "win32" else "uv"
    wheel = _make_wheel(
        tmp_path / "uv.whl",
        {f"uv-0.13.9.data/scripts/{exe_name}": b"MZ-fake-uv"},
    )
    monkeypatch.setattr(installer, "_platform_tags", lambda: ("win_amd64",))
    monkeypatch.setattr(
        installer,
        "_pypi_release",
        lambda *_a, **_kw: [_wheel_entry("uv-0.13.9-py3-none-win_amd64.whl")],
    )

    def fake_download(_url: str, dest: Path, **_kw: Any) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(wheel.read_bytes())

    monkeypatch.setattr(installer, "_download", fake_download)
    monkeypatch.setattr(installer, "_run", _fake_run_factory(stdout="uv 0.13.9\n"))

    exe = installer.install_uv()
    assert exe == uv_executable()
    assert exe.read_bytes() == b"MZ-fake-uv"


def test_install_python_tool_creates_venv_and_records(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_uv = tools_root / "uv" / "uv.exe"
    fake_uv.parent.mkdir(parents=True, exist_ok=True)
    fake_uv.write_text("", encoding="utf-8")
    monkeypatch.setattr(installer, "install_uv", lambda _progress=None: fake_uv)
    monkeypatch.setattr(
        installer,
        "_run",
        _fake_run_factory(stdout="0.4.0\n", on_venv=paths_venv("basic-pitch")),
    )

    python = installer.install_python_tool(installer.tool_spec("basic-pitch"))
    assert python == venv_python("basic-pitch")
    assert python.is_file()
    manifest = json.loads(manifest_file().read_text(encoding="utf-8"))
    assert manifest["tools"]["basic-pitch"]["version"] == "0.4.0"


def paths_venv(tool_id: str) -> Path:
    from lyraforge.toolchain.paths import venv_dir

    return venv_dir(tool_id)


def test_install_unknown_tool_is_rejected(tools_root: Path) -> None:
    with pytest.raises(LyraError) as exc:
        installer.install("nope")
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT


def test_managed_env_injects_managed_paths_and_respects_user_values(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed_ffmpeg = ffmpeg_executable()
    managed_ffmpeg.parent.mkdir(parents=True, exist_ok=True)
    managed_ffmpeg.write_bytes(b"MZ")
    managed_python = venv_python("dettato")
    managed_python.parent.mkdir(parents=True, exist_ok=True)
    managed_python.write_text("", encoding="utf-8")
    _write_manifest(
        {
            "ffmpeg": {"mode": "managed", "path": str(managed_ffmpeg), "version": "9.0.2"},
            "dettato": {"mode": "managed", "path": str(managed_python), "version": "2.0.0"},
        }
    )

    env = runtime.managed_env({"PATH": "C:/windows"})
    assert env["LYRAFORGE_FFMPEG_BIN"] == str(managed_ffmpeg)
    assert env["PATH"].startswith(str(managed_ffmpeg.parent))
    assert env["LYRAFORGE_DETTATO_PYTHON"] == str(managed_python)

    override = runtime.managed_env(
        {"PATH": "", "LYRAFORGE_FFMPEG_BIN": "/custom/ffmpeg", "LYRAFORGE_DETTATO_PYTHON": "/x"}
    )
    assert override["LYRAFORGE_FFMPEG_BIN"] == "/custom/ffmpeg"
    assert override["LYRAFORGE_DETTATO_PYTHON"] == "/x"


def test_apply_process_env_is_noop_without_manifest(
    tools_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LYRAFORGE_FFMPEG_BIN", raising=False)
    runtime.apply_process_env()
    assert "LYRAFORGE_FFMPEG_BIN" not in os.environ
