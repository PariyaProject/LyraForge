"""Download and install the optional external toolchain into a user-owned directory.

Everything happens under ``%LOCALAPPDATA%\\LyraForge\\tools`` (or the platform equivalent):
* ``uv`` is bootstrapped from its official PyPI wheel (SHA-256 verified, extracted, version
  checked) and keeps its managed CPython and cache inside the same directory;
* FFmpeg is extracted from the SHA-256 verified ``imageio-ffmpeg`` wheel;
* Basic Pitch and dettato live in their own virtualenvs, never in LyraForge's runtime.

No system-wide environment variable, registry entry or PATH change is performed. The
application injects the managed paths into its child processes at startup
(:mod:`lyraforge.toolchain.runtime`).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.fs import atomic_write_text
from lyraforge.toolchain.paths import (
    downloads_dir,
    ffmpeg_executable,
    manifest_file,
    tools_dir,
    uv_env,
    uv_executable,
    venv_dir,
    venv_python,
)
from lyraforge.toolchain.specs import TOOL_SPECS, ToolSpec, tool_ids, tool_spec

ProgressCallback = Callable[[float, str], None]

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
USER_AGENT = "LyraForge-Toolchain/1.0 (+https://github.com/PariyaProject/LyraForge)"
UV_VERSION = "0.13.9"
IMAGEIO_FFMPEG_VERSION = "0.8.1"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
_INSTALL_LOCK = threading.Lock()


# --------------------------------------------------------------------------- helpers


def _emit(progress: ProgressCallback | None, fraction: float, message: str) -> None:
    if progress is not None:
        progress(max(0.0, min(1.0, fraction)), message)


def _run(
    cmd: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(cmd),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"{Path(cmd[0]).name} timed out after {timeout:.0f}s",
        ) from exc
    except OSError as exc:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE, f"cannot run {Path(cmd[0]).name}: {exc}"
        ) from exc


def _tail(text: str, limit: int = 600) -> str:
    clean = (text or "").strip()
    return clean[-limit:] if len(clean) > limit else clean


def _platform_tags() -> tuple[str, ...]:
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if sys.platform == "win32":
        return ("win_arm64",) if arm else ("win_amd64",)
    if sys.platform == "darwin":
        if arm:
            return (
                "macosx_11_0_arm64",
                "macosx_12_0_arm64",
                "universal2",
                "macosx_10_9_x86_64",
            )
        return ("macosx_10_9_x86_64", "macosx_10_15_x86_64", "universal2")
    if arm:
        return ("manylinux_2_17_aarch64", "manylinux2014_aarch64", "manylinux_2_28_aarch64")
    return (
        "manylinux_2_17_x86_64",
        "manylinux2014_x86_64",
        "manylinux_2_28_x86_64",
        "manylinux1_x86_64",
    )


def _pypi_release(name: str, version: str) -> list[dict[str, Any]]:
    import json as _json
    from urllib.request import urlopen as _urlopen

    url = PYPI_JSON_URL.format(name=name, version=version)
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"unexpected PyPI host: {parsed.hostname}")
    try:
        with _urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as resp:  # noqa: S310
            payload = _json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"cannot query PyPI for {name}=={version}: {exc}",
        ) from exc
    files = payload.get("urls")
    if not isinstance(files, list) or not files:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE, f"PyPI returned no files for {name}=={version}"
        )
    return files


def _pick_wheel(files: Sequence[dict[str, Any]], tags: Sequence[str]) -> dict[str, Any]:
    for tag in tags:
        for item in files:
            filename = str(item.get("filename", ""))
            if filename.endswith(".whl") and tag in filename:
                return item
    raise LyraError(
        ErrorCode.MODEL_MISSING,
        f"no wheel matches this platform ({', '.join(tags)}); install the tool manually",
    )


def _download(
    url: str,
    dest: Path,
    *,
    expected_sha256: str,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"refusing download from {parsed.netloc}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as resp, (  # noqa: S310
            dest.open("wb")
        ) as handle:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise LyraError(
                        ErrorCode.LIMIT_EXCEEDED,
                        f"download exceeds {max_bytes // (1024 * 1024)} MiB limit",
                    )
                digest.update(chunk)
                handle.write(chunk)
    except LyraError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, f"download failed: {exc}") from exc

    if digest.hexdigest().lower() != expected_sha256.lower():
        dest.unlink(missing_ok=True)
        raise LyraError(
            ErrorCode.PACKAGE_INVALID,
            "downloaded file failed SHA-256 verification; aborting for safety",
        )


# --------------------------------------------------------------------------- manifest


def _load_manifest() -> dict[str, Any]:
    path = manifest_file()
    if not path.is_file():
        return {"version": 1, "tools": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "tools": {}}
    if not isinstance(data, dict) or not isinstance(data.get("tools"), dict):
        return {"version": 1, "tools": {}}
    return data


def load_manifest() -> dict[str, Any]:
    """Public accessor for the toolchain manifest (used by the runtime injector)."""
    return _load_manifest()


def get_tool_setting(key: str, default: Any = None) -> Any:
    settings = _load_manifest().get("settings")
    if isinstance(settings, dict):
        return settings.get(key, default)
    return default


def set_tool_setting(key: str, value: Any) -> None:
    data = _load_manifest()
    data.setdefault("settings", {})[key] = value
    data["version"] = 1
    atomic_write_text(manifest_file(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _record(tool_id: str, *, path: Path, version: str, mode: str = "managed") -> None:
    data = _load_manifest()
    data.setdefault("tools", {})[tool_id] = {
        "mode": mode,
        "path": str(path),
        "version": version,
        "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    data["version"] = 1
    atomic_write_text(manifest_file(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- installers


def _uv_works(exe: Path) -> bool:
    if not exe.is_file():
        return False
    res = _run([str(exe), "--version"], timeout=60)
    return res.returncode == 0


def install_uv(progress: ProgressCallback | None = None) -> Path:
    """Ensure a SHA-256 verified ``uv`` binary exists; return its path."""
    exe = uv_executable()
    if _uv_works(exe):
        _emit(progress, 0.1, "uv 已就绪")
        return exe

    _emit(progress, 0.05, "查询 uv 发行版…")
    release = _pypi_release("uv", UV_VERSION)
    wheel = _pick_wheel(release, _platform_tags())
    wheel_path = downloads_dir() / "uv.whl"
    _emit(progress, 0.1, f"下载 uv {UV_VERSION} ({wheel.get('filename')})…")
    _download(
        str(wheel["url"]),
        wheel_path,
        expected_sha256=str(wheel["digests"]["sha256"]),
        max_bytes=80 * 1024 * 1024,
    )

    exe.parent.mkdir(parents=True, exist_ok=True)
    exe_name = exe.name
    _emit(progress, 0.3, "解压 uv…")
    with zipfile.ZipFile(wheel_path) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(f".data/scripts/{exe_name}")
            ),
            None,
        )
        if member is None:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID, f"uv wheel does not contain {exe_name}"
            )
        with archive.open(member) as src, exe.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    wheel_path.unlink(missing_ok=True)
    if sys.platform != "win32":
        exe.chmod(0o755)

    if not _uv_works(exe):
        raise LyraError(ErrorCode.SOURCE_UNAVAILABLE, "downloaded uv binary failed to run")
    _emit(progress, 0.4, "uv 安装完成")
    return exe


def install_ffmpeg(progress: ProgressCallback | None = None) -> Path:
    """Extract a verified FFmpeg binary from the imageio-ffmpeg wheel."""
    target = ffmpeg_executable()
    if target.is_file():
        res = _run([str(target), "-version"], timeout=60)
        if res.returncode == 0:
            _emit(progress, 1.0, "FFmpeg 已就绪")
            _record("ffmpeg", path=target, version=_first_line(res.stdout))
            return target

    _emit(progress, 0.05, "查询 FFmpeg 发行版…")
    release = _pypi_release("imageio-ffmpeg", IMAGEIO_FFMPEG_VERSION)
    wheel = _pick_wheel(release, _platform_tags())
    wheel_path = downloads_dir() / "imageio-ffmpeg.whl"
    _emit(progress, 0.1, "下载 FFmpeg（约 40 MB）…")
    _download(
        str(wheel["url"]),
        wheel_path,
        expected_sha256=str(wheel["digests"]["sha256"]),
        max_bytes=120 * 1024 * 1024,
    )

    _emit(progress, 0.7, "解压 FFmpeg…")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_path) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if "/binaries/ffmpeg-" in name and name.endswith((".exe", ""))
            ),
            None,
        )
        if member is None:
            raise LyraError(
                ErrorCode.PACKAGE_INVALID, "imageio-ffmpeg wheel does not contain an ffmpeg binary"
            )
        with archive.open(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    wheel_path.unlink(missing_ok=True)
    if sys.platform != "win32":
        target.chmod(0o755)

    res = _run([str(target), "-version"], timeout=60)
    if res.returncode != 0:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"installed FFmpeg does not run: {_tail(res.stderr)}",
        )
    version = _ffmpeg_version(res.stdout)
    _record("ffmpeg", path=target, version=version)
    _emit(progress, 1.0, f"FFmpeg {version} 已安装")
    return target


def _ffmpeg_version(stdout: str) -> str:
    match = re.search(r"ffmpeg version (\S+)", stdout or "")
    return match.group(1) if match else _first_line(stdout)


def install_python_tool(spec: ToolSpec, progress: ProgressCallback | None = None) -> Path:
    """Create an isolated virtualenv and install the pinned packages for ``spec``."""
    uv = install_uv(progress)
    target_dir = venv_dir(spec.id)
    python = venv_python(spec.id)

    _emit(progress, 0.45, f"创建 {spec.display_name} 独立环境…")
    res = _run(
        [
            str(uv),
            "venv",
            str(target_dir),
            "--python",
            "3.11",
            "--python-preference",
            "managed",
            "--clear",
        ],
        env=uv_env(),
        timeout=1800,
    )
    if res.returncode != 0:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"cannot create virtualenv for {spec.id}: {_tail(res.stderr)}",
        )

    _emit(progress, 0.6, f"安装 {spec.display_name} 依赖（首次可能数分钟）…")
    res = _run(
        [str(uv), "pip", "install", "--python", str(python), *spec.packages],
        env=uv_env(),
        timeout=3600,
    )
    if res.returncode != 0:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"pip install failed for {spec.id}: {_tail(res.stderr)}",
        )

    _emit(progress, 0.9, f"验证 {spec.id}…")
    res = _run([str(python), "-c", f"import {spec.probe_module}"], timeout=600)
    if res.returncode != 0:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"{spec.id} installed but failed to import: {_tail(res.stderr)}",
        )

    version = _installed_version(python, spec.dist_name)
    _record(spec.id, path=python, version=version)
    _emit(progress, 1.0, f"{spec.display_name} {version} 已安装")
    return python


def _installed_version(python: Path, dist_name: str) -> str:
    if not dist_name:
        return "unknown"
    res = _run(
        [
            str(python),
            "-c",
            f"import importlib.metadata as m;print(m.version({dist_name!r}))",
        ],
        timeout=120,
    )
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else "unknown"


def _first_line(text: str) -> str:
    line = (text or "").strip().splitlines()
    return line[0] if line else "unknown"


def install_dettato_gpu(progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Install a CUDA-enabled PyTorch build into the dettato virtualenv."""
    python = venv_python("dettato")
    if not python.is_file():
        raise LyraError(
            ErrorCode.MODEL_MISSING,
            "请先安装 dettato，再安装 GPU 加速版 PyTorch",
        )
    uv = install_uv(progress)
    index = os.environ.get(
        "LYRAFORGE_PYTORCH_CUDA_INDEX",
        "https://download.pytorch.org/whl/cu124",
    )
    _emit(progress, 0.2, f"下载并安装 CUDA 版 PyTorch（约 2.5 GB，索引 {index}）…")
    res = _run(
        [
            str(uv),
            "pip",
            "install",
            "--python",
            str(python),
            "--index-url",
            index,
            "--upgrade",
            "torch",
        ],
        env=uv_env(),
        timeout=7200,
    )
    if res.returncode != 0:
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            f"CUDA PyTorch 安装失败：{_tail(res.stderr)}",
        )
    _emit(progress, 0.9, "验证 CUDA 是否可用…")
    from lyraforge.toolchain.gpu import probe_dettato_torch

    probe = probe_dettato_torch()
    if probe is None or not probe.get("cuda_available"):
        raise LyraError(
            ErrorCode.SOURCE_UNAVAILABLE,
            "CUDA 版 PyTorch 已安装，但 torch.cuda.is_available() 仍为 False；"
            "请检查 NVIDIA 驱动与 CUDA 版本，或设置 LYRAFORGE_PYTORCH_CUDA_INDEX 使用匹配的索引。",
        )
    set_tool_setting("dettato_gpu", True)
    _emit(progress, 1.0, "dettato GPU 加速已就绪")
    return {"installed": True, "torch": probe}


def install(tool_id: str, progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Install one tool and return its fresh status entry."""
    if tool_id == "dettato-gpu":
        with _INSTALL_LOCK:
            install_dettato_gpu(progress)
        return {"tool_id": "dettato-gpu", "installed": True}
    spec = tool_spec(tool_id)
    if spec is None:
        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown tool: {tool_id!r}",
            {"available": list(tool_ids())},
        )
    with _INSTALL_LOCK:
        if spec.kind == "binary":
            install_ffmpeg(progress)
        else:
            install_python_tool(spec, progress)
    return next(item for item in status() if item["id"] == tool_id)


# --------------------------------------------------------------------------- status


def _system_python(spec: ToolSpec) -> Path | None:
    raw = os.environ.get(spec.env_var, "").strip()
    if raw and Path(raw).is_file():
        return Path(raw)
    return None


def status() -> list[dict[str, Any]]:
    """Return the install state of every known tool (cheap, no heavy probes)."""
    manifest = _load_manifest().get("tools", {})
    items: list[dict[str, Any]] = []
    for spec in TOOL_SPECS:
        entry = manifest.get(spec.id, {}) if isinstance(manifest, dict) else {}
        path: Path | None = None
        source: str | None = None
        version = str(entry.get("version") or "") or None

        if spec.kind == "binary":
            managed = ffmpeg_executable()
            if entry.get("mode") == "managed" and managed.is_file():
                path, source = managed, "managed"
            else:
                system = os.environ.get(spec.env_var, "").strip()
                found = Path(system) if system else None
                if found is None or not found.is_file():
                    which = shutil.which("ffmpeg")
                    found = Path(which) if which else None
                if found is not None and found.is_file():
                    path, source = found, "system"
                    version = None
        else:
            managed_python = venv_python(spec.id)
            if entry.get("mode") == "managed" and managed_python.is_file():
                path, source = managed_python, "managed"
            else:
                system_python = _system_python(spec)
                if system_python is not None:
                    path, source = system_python, "system"
                    version = None

        items.append(
            {
                "id": spec.id,
                "display_name": spec.display_name,
                "license": spec.license,
                "description": spec.description,
                "kind": spec.kind,
                "download_mb": spec.download_mb,
                "env_var": spec.env_var,
                "installed": path is not None,
                "source": source,
                "path": str(path) if path is not None else None,
                "version": version,
            }
        )
    return items


def tools_root() -> Path:
    """Expose the managed tools directory for UI/diagnostics."""
    return tools_dir()


__all__ = [
    "install",
    "install_ffmpeg",
    "install_python_tool",
    "install_uv",
    "load_manifest",
    "manifest_file",
    "status",
    "tools_root",
    "venv_dir",
]
