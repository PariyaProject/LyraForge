"""Inject managed toolchain paths into the process environment.

The installer deliberately never touches the user's system environment. Instead, when
LyraForge starts (CLI or desktop), this module exposes the managed binaries through the
same environment variables the existing adapters already understand, so nothing else has
to change. Explicit user-provided values always win over managed ones.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from lyraforge.toolchain.installer import load_manifest
from lyraforge.toolchain.paths import ffmpeg_executable, venv_python
from lyraforge.toolchain.specs import TOOL_SPECS


def managed_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return ``base`` (default ``os.environ``) plus managed toolchain overrides."""
    env = dict(os.environ if base is None else base)
    tools = load_manifest().get("tools", {})
    if not isinstance(tools, dict):
        tools = {}

    ffmpeg_entry = tools.get("ffmpeg") or {}
    managed_ffmpeg = ffmpeg_executable()
    if ffmpeg_entry.get("mode") == "managed" and managed_ffmpeg.is_file():
        env.setdefault("LYRAFORGE_FFMPEG_BIN", str(managed_ffmpeg))
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
        if str(managed_ffmpeg.parent) not in parts:
            env["PATH"] = os.pathsep.join([str(managed_ffmpeg.parent), *parts])

    for spec in TOOL_SPECS:
        if spec.kind != "python":
            continue
        entry = tools.get(spec.id) or {}
        python = venv_python(spec.id)
        if entry.get("mode") == "managed" and python.is_file():
            env.setdefault(spec.env_var, str(python))
    return env


def apply_process_env() -> None:
    """Apply :func:`managed_env` to ``os.environ`` (idempotent, never overrides user values)."""
    tools = load_manifest().get("tools", {})
    if not isinstance(tools, dict) or not tools:
        return
    for key, value in managed_env().items():
        current = os.environ.get(key)
        if key == "PATH":
            os.environ["PATH"] = value
        elif not current:
            os.environ[key] = value
