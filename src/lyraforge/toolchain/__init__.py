"""Optional external toolchain: detection, download-on-demand install and runtime wiring."""

from __future__ import annotations

from lyraforge.toolchain.installer import (
    install,
    install_ffmpeg,
    install_python_tool,
    install_uv,
    status,
    tools_root,
)
from lyraforge.toolchain.runtime import apply_process_env, managed_env
from lyraforge.toolchain.specs import TOOL_SPECS, ToolSpec, tool_ids, tool_spec

__all__ = [
    "TOOL_SPECS",
    "ToolSpec",
    "apply_process_env",
    "install",
    "install_ffmpeg",
    "install_python_tool",
    "install_uv",
    "managed_env",
    "status",
    "tool_ids",
    "tool_spec",
    "tools_root",
]
