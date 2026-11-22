"""Bounded-memory and bounded-disk subprocess execution utilities."""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.playback.guards import StopToken

MAX_SUBPROCESS_LOG_BYTES = 256 * 1024
DEFAULT_LOG_TAIL_BYTES = 8192
_PIPE_READ_CHUNK_BYTES = 4096


def read_file_tail(path: Path, max_bytes: int = DEFAULT_LOG_TAIL_BYTES) -> bytes:
    """Read only the trailing ``max_bytes`` of a file via ``seek()``."""
    if max_bytes <= 0 or not path.is_file():
        return b""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        offset = max(0, size - max_bytes)
        fh.seek(offset, os.SEEK_SET)
        return fh.read(max_bytes)


class _BoundedRotatingLog:
    """Two-segment size-capped rotating log that never holds full logs in RAM."""

    def __init__(self, base_path: Path, max_bytes: int = MAX_SUBPROCESS_LOG_BYTES) -> None:
        if max_bytes < 2048:
            raise ValueError("max_bytes must be >= 2048")
        self._curr_path = base_path
        self._prev_path = base_path.with_name(f"{base_path.name}.1")
        self._seg_limit = max_bytes // 2
        self._curr_size = 0
        self._prev_size = 0
        self.total_written = 0
        self.truncated = False
        self.peak_disk_bytes = 0
        self._lock = threading.Lock()
        self._fh: IO[bytes] | None = self._curr_path.open("wb")

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._fh is None:
                return
            self.total_written += len(chunk)
            data = chunk
            if len(data) > self._seg_limit:
                self.truncated = True
                data = data[-self._seg_limit :]
            if self._curr_size + len(data) > self._seg_limit and self._curr_size > 0:
                self._rotate_locked()
            self._fh.write(data)
            self._curr_size += len(data)
            self.peak_disk_bytes = max(self.peak_disk_bytes, self._prev_size + self._curr_size)

    def _rotate_locked(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        self.truncated = True
        os.replace(self._curr_path, self._prev_path)
        self._prev_size = self._curr_size
        self._curr_size = 0
        self._fh = self._curr_path.open("wb")

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                with contextlib.suppress(OSError):
                    self._fh.flush()
                with contextlib.suppress(OSError):
                    self._fh.close()
                self._fh = None

    def read_tail(self, tail_bytes: int = DEFAULT_LOG_TAIL_BYTES) -> tuple[bytes, bool, int]:
        self.close()
        curr_tail = read_file_tail(self._curr_path, tail_bytes)
        if len(curr_tail) < tail_bytes and self._prev_path.is_file():
            need = tail_bytes - len(curr_tail)
            prev_tail = read_file_tail(self._prev_path, need)
            combined = prev_tail + curr_tail
        else:
            combined = curr_tail
        return combined, self.truncated, self.total_written

    def cleanup(self) -> None:
        self.close()
        self._curr_path.unlink(missing_ok=True)
        self._prev_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class BoundedSubprocessResult:
    returncode: int
    stdout_tail: bytes
    stderr_tail: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_bytes: int
    stderr_bytes: int
    peak_disk_bytes: int


def _terminate_proc(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _drain_pipe(pipe: IO[bytes] | None, log: _BoundedRotatingLog) -> None:
    if pipe is None:
        return
    try:
        while True:
            try:
                chunk = pipe.read(_PIPE_READ_CHUNK_BYTES)
            except TypeError:
                chunk = pipe.read()
                if chunk:
                    log.write(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
                break
            if not chunk:
                break
            log.write(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    except (OSError, ValueError):
        pass
    finally:
        close_fn = getattr(pipe, "close", None)
        if callable(close_fn):
            with contextlib.suppress(OSError):
                close_fn()


def format_log_tail(
    stderr_tail: bytes,
    stdout_tail: bytes,
    *,
    stderr_truncated: bool = False,
    stderr_bytes: int = 0,
) -> str:
    """Format diagnostic stderr/stdout tail cleanly without unbounded text."""
    text = stderr_tail.decode("utf-8", errors="replace").strip()
    if not text and stdout_tail:
        text = stdout_tail.decode("utf-8", errors="replace").strip()
    if not text:
        text = "non-zero exit"
    if stderr_truncated:
        text = f"[stderr truncated to trailing bytes; total={stderr_bytes} bytes] {text}"
    return text


def run_bounded_subprocess(
    cmd: Sequence[str],
    *,
    work_dir: Path,
    prefix: str,
    timeout_s: float,
    stop_token: StopToken | None,
    cancel_message: str,
    timeout_code: ErrorCode,
    timeout_message: str,
    max_log_bytes: int = MAX_SUBPROCESS_LOG_BYTES,
    tail_bytes: int = DEFAULT_LOG_TAIL_BYTES,
) -> BoundedSubprocessResult:
    """Run subprocess with concurrent pipe drains and rotating disk-bounded logs."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_log = _BoundedRotatingLog(work_dir / f".{prefix}.stdout.log", max_bytes=max_log_bytes)
    err_log = _BoundedRotatingLog(work_dir / f".{prefix}.stderr.log", max_bytes=max_log_bytes)
    t_out: threading.Thread | None = None
    t_err: threading.Thread | None = None
    proc: subprocess.Popen[bytes] | None = None

    try:
        proc = subprocess.Popen(  # noqa: S603
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        stdout_pipe = getattr(proc, "stdout", None)
        stderr_pipe = getattr(proc, "stderr", None)
        t_out = threading.Thread(
            target=_drain_pipe,
            args=(stdout_pipe, out_log),
            name=f"{prefix}-stdout-drain",
            daemon=True,
        )
        t_err = threading.Thread(
            target=_drain_pipe,
            args=(stderr_pipe, err_log),
            name=f"{prefix}-stderr-drain",
            daemon=True,
        )
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + float(timeout_s)
        while proc.poll() is None:
            if stop_token is not None and stop_token.stopped:
                _terminate_proc(proc)
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, cancel_message)
            if time.monotonic() > deadline:
                _terminate_proc(proc)
                raise LyraError(timeout_code, timeout_message)
            time.sleep(0.05)

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)
        stdout_tail, stdout_trunc, stdout_total = out_log.read_tail(tail_bytes)
        stderr_tail, stderr_trunc, stderr_total = err_log.read_tail(tail_bytes)
        return BoundedSubprocessResult(
            returncode=int(proc.returncode or 0),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            stdout_truncated=stdout_trunc,
            stderr_truncated=stderr_trunc,
            stdout_bytes=stdout_total,
            stderr_bytes=stderr_total,
            peak_disk_bytes=max(out_log.peak_disk_bytes, err_log.peak_disk_bytes),
        )
    finally:
        if proc is not None:
            if proc.poll() is None:
                _terminate_proc(proc)
            for pipe_attr in ("stdout", "stderr"):
                pipe_obj = getattr(proc, pipe_attr, None)
                close_fn = getattr(pipe_obj, "close", None)
                if callable(close_fn):
                    with contextlib.suppress(OSError):
                        close_fn()
        if t_out is not None and t_out.is_alive():
            t_out.join(timeout=0.5)
        if t_err is not None and t_err.is_alive():
            t_err.join(timeout=0.5)
        out_log.cleanup()
        err_log.cleanup()
