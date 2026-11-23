"""Filesystem layout for the managed external toolchain."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lyraforge.library.paths import default_data_dir

TOOLS_DIR_ENV = "LYRAFORGE_TOOLS_DIR"
MANIFEST_FILENAME = "toolchain.json"
MANIFEST_VERSION = 1


def tools_dir() -> Path:
    """Return the per-user directory holding managed external tools."""
    override = os.environ.get(TOOLS_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_dir() / "tools"


def manifest_file() -> Path:
    return tools_dir() / MANIFEST_FILENAME


def uv_executable() -> Path:
    name = "uv.exe" if sys.platform == "win32" else "uv"
    return tools_dir() / "uv" / name


def venv_dir(tool_id: str) -> Path:
    return tools_dir() / tool_id


def venv_python(tool_id: str) -> Path:
    if sys.platform == "win32":
        return venv_dir(tool_id) / "Scripts" / "python.exe"
    return venv_dir(tool_id) / "bin" / "python"


def ffmpeg_executable() -> Path:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    return tools_dir() / "ffmpeg" / name


def downloads_dir() -> Path:
    return tools_dir() / ".downloads"


def uv_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment that keeps uv's Python/cache payload inside LyraForge's tools dir."""
    env = dict(os.environ if base is None else base)
    env["UV_PYTHON_INSTALL_DIR"] = str(tools_dir() / "python")
    env["UV_CACHE_DIR"] = str(tools_dir() / "cache")
    env["UV_NO_CONFIG"] = "1"
    env["UV_LINK_MODE"] = "copy"
    return env
