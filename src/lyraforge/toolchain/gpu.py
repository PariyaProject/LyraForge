"""GPU detection and dettato device preference for the optional toolchain."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from lyraforge.media.subprocess_utils import hidden_subprocess_kwargs
from lyraforge.toolchain.installer import get_tool_setting, set_tool_setting
from lyraforge.toolchain.paths import venv_python

DEVICE_ENV = "LYRAFORGE_DETTATO_DEVICE"
VALID_DEVICES = frozenset({"auto", "cpu", "cuda", "mps"})

_TORCH_PROBE = (
    "import json, torch;"
    "print(json.dumps({"
    "'torch': torch.__version__,"
    "'cuda': torch.version.cuda,"
    "'available': bool(torch.cuda.is_available()),"
    "'devices': torch.cuda.device_count()"
    "}))"
)


def detect_nvidia() -> dict[str, Any]:
    """Detect an NVIDIA GPU from the public ``nvidia-smi`` query tool."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"present": False, "name": None, "driver": None}
    try:
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [exe, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"present": False, "name": None, "driver": None}
    first = next((line for line in res.stdout.splitlines() if line.strip()), "")
    if res.returncode != 0 or not first:
        return {"present": False, "name": None, "driver": None}
    parts = [part.strip() for part in first.split(",")]
    return {
        "present": True,
        "name": parts[0] if parts else None,
        "driver": parts[1] if len(parts) > 1 else None,
    }


def probe_torch_env(tool_id: str) -> dict[str, Any] | None:
    """Return the torch build/availability inside an isolated tool virtualenv, if present."""
    python = venv_python(tool_id)
    if not python.is_file():
        return None
    try:
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [str(python), "-c", _TORCH_PROBE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    try:
        data = json.loads(res.stdout.strip() or "{}")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "version": data.get("torch"),
        "cuda_build": data.get("cuda"),
        "cuda_available": bool(data.get("available")),
        "device_count": int(data.get("devices") or 0),
    }


def probe_dettato_torch() -> dict[str, Any] | None:
    """Return the torch build/availability inside the dettato virtualenv, if present."""
    return probe_torch_env("dettato")


def probe_demucs_torch() -> dict[str, Any] | None:
    """Return the torch build/availability inside the demucs virtualenv, if present."""
    return probe_torch_env("demucs")


def device_setting() -> str:
    value = str(get_tool_setting("dettato_device", "auto") or "auto").lower()
    return value if value in VALID_DEVICES else "auto"


def set_device(device: str) -> dict[str, Any]:
    """Persist the device preference and apply it to the current process."""
    value = device.strip().lower()
    if value not in VALID_DEVICES:
        from lyraforge.errors import ErrorCode, LyraError

        raise LyraError(
            ErrorCode.INVALID_ARGUMENT,
            f"dettato device must be one of {sorted(VALID_DEVICES)}",
        )
    set_tool_setting("dettato_device", value)
    for env_key in (DEVICE_ENV, "LYRAFORGE_DEMUCS_DEVICE"):
        if value == "auto":
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = value
    return gpu_status()


def gpu_status() -> dict[str, Any]:
    return {
        "nvidia": detect_nvidia(),
        "dettato_installed": venv_python("dettato").is_file(),
        "dettato_torch": probe_dettato_torch(),
        "demucs_installed": venv_python("demucs").is_file(),
        "demucs_torch": probe_demucs_torch(),
        "device": device_setting(),
        "device_env": DEVICE_ENV,
    }


__all__ = [
    "DEVICE_ENV",
    "VALID_DEVICES",
    "detect_nvidia",
    "device_setting",
    "gpu_status",
    "probe_demucs_torch",
    "probe_dettato_torch",
    "probe_torch_env",
    "set_device",
]
