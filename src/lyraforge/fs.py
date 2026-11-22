"""Atomic filesystem helpers (leaf module: depends only on errors)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a sibling temporary file and atomically replace ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 LF text atomically to ``path``."""
    atomic_write_bytes(path, text.encode("utf-8"))


def resolve_under(root: Path, rel: str) -> Path:
    """Resolve a stored relative path under ``root``, blocking traversal."""
    if not rel or Path(rel).is_absolute():
        raise LyraError(ErrorCode.PACKAGE_INVALID, f"invalid relative path: {rel!r}")
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    if not candidate.is_relative_to(root_resolved) or candidate == root_resolved:
        raise LyraError(
            ErrorCode.PACKAGE_INVALID,
            f"path escapes data directory: {rel!r}",
            {"rel": rel},
        )
    return candidate
