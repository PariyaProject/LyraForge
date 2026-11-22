"""Unified error codes (PROJECT_SPEC §12.4).

Pure module: no I/O, safe to import from any layer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # Codes listed in PROJECT_SPEC §12.4
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    MEDIA_DECODE_FAILED = "MEDIA_DECODE_FAILED"
    MODEL_MISSING = "MODEL_MISSING"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    NO_PLAYABLE_NOTES = "NO_PLAYABLE_NOTES"
    PROFILE_INVALID = "PROFILE_INVALID"
    GAME_NOT_FOCUSED = "GAME_NOT_FOCUSED"
    PLAYBACK_ABORTED = "PLAYBACK_ABORTED"
    DISK_FULL = "DISK_FULL"
    PACKAGE_INVALID = "PACKAGE_INVALID"
    # M0 additions (documented in docs/ARCHITECTURE.md)
    MEDIA_UNSUPPORTED = "MEDIA_UNSUPPORTED"  # valid file, unsupported variant (SMF type 2, SMPTE)
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"  # size / note-count / duration guards
    PERFORMANCE_INVALID = "PERFORMANCE_INVALID"  # performance.json failed schema/semantic checks
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    LIBRARY_BUSY = "LIBRARY_BUSY"  # library locked or under exclusive restore/shutdown maintenance


class LyraError(Exception):
    """Domain error carrying a stable machine-readable code."""

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": str(self.code), "message": self.message, "details": self.details}
