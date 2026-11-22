"""Atomic filesystem helpers (leaf module: depends only on errors)."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

from lyraforge.errors import ErrorCode, LyraError

_PATH_STRIPES = [threading.Lock() for _ in range(64)]


def _stripe_lock(path: Path) -> threading.Lock:
    idx = hash(os.path.normcase(os.path.abspath(os.fspath(path)))) % len(_PATH_STRIPES)
    return _PATH_STRIPES[idx]


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a sibling temporary file and atomically replace ``path``."""
    with _stripe_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt >= 4:
                        raise
                    time.sleep(0.015 * (attempt + 1))
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
    raw_target = root_resolved / rel
    for attempt in range(3):
        candidate = raw_target.resolve()
        if candidate.is_relative_to(root_resolved) and candidate != root_resolved:
            return candidate
        # Retry briefly if Windows _getfinalpathname saw an in-flight replace
        if attempt < 2 and ".." not in Path(rel).parts:
            time.sleep(0.01)
            continue
        break
    raise LyraError(
        ErrorCode.PACKAGE_INVALID,
        f"path escapes data directory: {rel!r}",
        {"rel": rel},
    )
