"""Cross-platform local storage paths and atomic file I/O."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lyraforge.fs import atomic_write_bytes, atomic_write_text, resolve_under

DATA_DIR_ENV = "LYRAFORGE_DATA_DIR"
APP_DIR_NAME = "LyraForge"


def default_data_dir() -> Path:
    """Return the platform-standard user data directory for LyraForge."""
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / APP_DIR_NAME


__all__ = [
    "APP_DIR_NAME",
    "DATA_DIR_ENV",
    "atomic_write_bytes",
    "atomic_write_text",
    "default_data_dir",
    "resolve_under",
]
