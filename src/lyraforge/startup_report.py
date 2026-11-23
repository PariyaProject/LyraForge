"""Fatal-startup diagnostics for the packaged desktop application.

The Windows release ships as a PyInstaller windowed executable (``console=False``):
it has no console, so any unrecoverable startup failure used to end the process
within a second and look exactly like "nothing happens". Every fatal startup path
now appends a timestamped traceback to a per-user log file and shows a native error
dialog, so the cause is visible without attaching a debugger.
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

LOG_FILENAME = "startup.log"
_DIALOG_TITLE = "LyraForge could not start"
_MAX_LOG_BYTES = 1024 * 1024


def startup_log_path() -> Path:
    """Return the per-user log file path used for unhandled startup failures."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "LyraForge" / "logs" / LOG_FILENAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "LyraForge" / LOG_FILENAME
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "lyraforge" / "logs" / LOG_FILENAME


def write_startup_log(message: str) -> Path | None:
    """Append ``message`` to the startup log; never raise (best-effort diagnostics)."""
    path = startup_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > _MAX_LOG_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
        return path
    except OSError:
        return None


def _show_windows_message_box(title: str, message: str) -> bool:
    try:
        import ctypes

        # MB_ICONERROR (0x10) | MB_TOPMOST (0x40000) | MB_SETFOREGROUND (0x10000)
        flags = 0x00000010 | 0x00040000 | 0x00010000
        ctypes.windll.user32.MessageBoxW(0, message, title, flags)  # type: ignore[attr-defined]
        return True
    except Exception:  # pragma: no cover - GUI failure must never mask the original error
        return False


def _show_macos_alert(title: str, message: str) -> bool:
    script = (
        "on run argv\n"
        "display alert (item 1 of argv) message (item 2 of argv) as critical\n"
        "end run"
    )
    try:
        subprocess.run(  # noqa: S603 - fixed executable, no shell, bounded timeout
            ["osascript", "-e", script, title, message],
            check=False,
            capture_output=True,
            timeout=15,
        )
        return True
    except Exception:  # pragma: no cover - GUI failure must never mask the original error
        return False


def show_error_dialog(title: str, message: str) -> bool:
    """Show a native blocking error dialog when the platform supports it."""
    if sys.platform == "win32":
        return _show_windows_message_box(title, message)
    if sys.platform == "darwin":
        return _show_macos_alert(title, message)
    return False


def describe_error(error: BaseException) -> str:
    """Return a one-line human-readable summary for ``error``."""
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    if code is not None and message is not None:
        return f"[{code}] {message}"
    text = str(error).strip()
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def report_startup_failure(
    error: BaseException,
    *,
    argv: Sequence[str] | None = None,
) -> Path | None:
    """Log ``error`` with a traceback and surface it in a native dialog."""
    summary = describe_error(error)
    invoked_as = " ".join(str(part) for part in (sys.argv if argv is None else argv)) or "<unknown>"
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    log_path = write_startup_log(f"FATAL {summary}\ncommand: {invoked_as}\n{detail}")

    lines = [summary]
    first_frame = _first_traceback_line(detail)
    if first_frame:
        lines.append(first_frame)
    if log_path is not None:
        lines.append(f"Details were written to:\n{log_path}")
    show_error_dialog(_DIALOG_TITLE, "\n\n".join(lines))
    return log_path


def _first_traceback_line(detail: str) -> str:
    """Return the innermost stack-frame line so the dialog names the failing location."""
    for line in reversed(detail.strip().splitlines()):
        stripped = line.strip()
        if stripped.startswith('File "'):
            return stripped[:400]
    return ""
