"""Bounded-memory and bounded-disk subprocess execution utilities."""

from __future__ import annotations

import contextlib
import os
import selectors
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

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
        self._closed = False
        self._lock = threading.Lock()
        self._fh: IO[bytes] | None = self._curr_path.open("wb")

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._closed or self._fh is None:
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

    def _close_locked(self) -> None:
        self._closed = True
        if self._fh is not None:
            with contextlib.suppress(OSError):
                self._fh.flush()
            with contextlib.suppress(OSError):
                self._fh.close()
            self._fh = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def read_tail(self, tail_bytes: int = DEFAULT_LOG_TAIL_BYTES) -> tuple[bytes, bool, int]:
        with self._lock:
            self._close_locked()
            curr_path = self._curr_path
            prev_path = self._prev_path
            truncated = self.truncated
            total_written = self.total_written
        curr_tail = read_file_tail(curr_path, tail_bytes)
        if len(curr_tail) < tail_bytes and prev_path.is_file():
            need = tail_bytes - len(curr_tail)
            prev_tail = read_file_tail(prev_path, need)
            combined = prev_tail + curr_tail
        else:
            combined = curr_tail
        return combined, truncated, total_written

    def cleanup(self) -> None:
        self.close()
        for p in (self._curr_path, self._prev_path):
            for idx in range(5):
                try:
                    p.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if idx + 1 >= 5:
                        break
                    time.sleep(0.03)


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


def _popen_isolation_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "close_fds": True,
    }
    if os.name == "nt":
        create_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if create_group:
            kwargs["creationflags"] = create_group
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _pgid_has_live_processes(pgid: int) -> bool:
    if os.name == "nt" or pgid <= 0:
        return False
    killpg_fn = getattr(os, "killpg", None)
    if not callable(killpg_fn):
        return False
    try:
        killpg_fn(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _kill_windows_descendants(pid: int, *, created_after_epoch: float | None = None) -> None:
    if os.name != "nt" or pid <= 0:
        return
    cutoff_unix = int((created_after_epoch or time.time()) - 5.0)
    ps_script = (
        "$q = New-Object System.Collections.Generic.Queue[int];"
        f"$q.Enqueue({pid});"
        "$seen = New-Object System.Collections.Generic.HashSet[int];"
        "$all = Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,CreationDate;"
        "$cutoff = ([DateTime]'1970-01-01T00:00:00Z').ToUniversalTime()"
        f".AddSeconds({cutoff_unix});"
        "while ($q.Count -gt 0) {"
        "$p = $q.Dequeue();"
        "foreach ($c in $all) {"
        "if ($c.ParentProcessId -eq $p -and "
        "(-not $c.CreationDate -or $c.CreationDate.ToUniversalTime() -ge $cutoff) -and "
        "$seen.Add([int]$c.ProcessId)) {"
        "$q.Enqueue([int]$c.ProcessId);"
        "Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue;"
        "}}}"
    )
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=6.0,
            check=False,
        )


def _join_threads(threads: Sequence[threading.Thread | None], timeout_s: float) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    for th in threads:
        if th is None or not th.is_alive():
            continue
        th.join(timeout=max(0.0, deadline - time.monotonic()))


def _terminate_process_tree(
    proc: Any,
    *,
    pgid: int | None = None,
    created_after_epoch: float | None = None,
    grace_s: float = 0.8,
) -> None:
    poll_fn = getattr(proc, "poll", None)
    term_fn = getattr(proc, "terminate", None)
    wait_fn = getattr(proc, "wait", None)
    kill_fn = getattr(proc, "kill", None)
    pid = getattr(proc, "pid", None)
    is_mock_or_dead = not (isinstance(pid, int) and pid > 0)

    if os.name == "nt":
        tk_res: subprocess.CompletedProcess[bytes] | None = None
        if not is_mock_or_dead:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                tk_res = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                )
        if callable(poll_fn) and poll_fn() is None:
            if callable(term_fn):
                with contextlib.suppress(OSError):
                    term_fn()
            if callable(wait_fn):
                try:
                    wait_fn(timeout=grace_s)
                except (subprocess.TimeoutExpired, TypeError):
                    if callable(kill_fn):
                        with contextlib.suppress(OSError):
                            kill_fn()
                    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                        wait_fn(timeout=2.0)
        if not is_mock_or_dead and (tk_res is None or tk_res.returncode != 0):
            _kill_windows_descendants(pid, created_after_epoch=created_after_epoch)
        return

    killpg_fn = getattr(os, "killpg", None)
    if pgid is not None and callable(killpg_fn):
        with contextlib.suppress(ProcessLookupError, OSError):
            killpg_fn(pgid, signal.SIGTERM)

    if callable(poll_fn) and poll_fn() is None and callable(term_fn):
        with contextlib.suppress(OSError):
            term_fn()

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        proc_alive = callable(poll_fn) and poll_fn() is None
        pg_alive = pgid is not None and _pgid_has_live_processes(pgid)
        if not proc_alive and not pg_alive:
            if callable(wait_fn):
                with contextlib.suppress(OSError, subprocess.TimeoutExpired, TypeError):
                    wait_fn(timeout=0.5)
            return
        time.sleep(0.02)

    if pgid is not None and callable(killpg_fn):
        with contextlib.suppress(ProcessLookupError, OSError):
            killpg_fn(pgid, signal.SIGKILL)
    if callable(poll_fn) and poll_fn() is None and callable(kill_fn):
        with contextlib.suppress(OSError):
            kill_fn()
    if callable(wait_fn):
        with contextlib.suppress(OSError, subprocess.TimeoutExpired, TypeError):
            wait_fn(timeout=2.0)


def _safe_terminate_process_tree(
    proc: Any,
    *,
    pgid: int | None = None,
    created_after_epoch: float | None = None,
    grace_s: float = 0.8,
) -> None:
    try:
        _terminate_process_tree(
            proc,
            pgid=pgid,
            created_after_epoch=created_after_epoch,
            grace_s=grace_s,
        )
    except Exception:  # noqa: BLE001
        killpg_fn = getattr(os, "killpg", None)
        if os.name != "nt" and pgid is not None and callable(killpg_fn):
            with contextlib.suppress(OSError):
                killpg_fn(pgid, signal.SIGKILL)
        kill_fn = getattr(proc, "kill", None)
        if callable(kill_fn):
            with contextlib.suppress(OSError):
                kill_fn()
        wait_fn = getattr(proc, "wait", None)
        if callable(wait_fn):
            with contextlib.suppress(OSError, subprocess.TimeoutExpired, TypeError):
                wait_fn(timeout=1.0)


def _pipe_selectable_fd(pipe: IO[bytes]) -> int | None:
    if os.name == "nt":
        return None
    fileno_fn = getattr(pipe, "fileno", None)
    if not callable(fileno_fn):
        return None
    try:
        fd = int(fileno_fn())
    except (OSError, TypeError, ValueError):
        return None
    if fd < 0:
        return None
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return None
    except OSError:
        return None
    return fd


def _drain_pipe(
    pipe: IO[bytes] | None,
    log: _BoundedRotatingLog,
    stop_event: threading.Event,
) -> None:
    if pipe is None:
        return
    try:
        fd = _pipe_selectable_fd(pipe)
        if fd is not None:
            with selectors.DefaultSelector() as sel:
                sel.register(fd, selectors.EVENT_READ)
                while not stop_event.is_set():
                    if not sel.select(timeout=0.05):
                        continue
                    try:
                        chunk = os.read(fd, _PIPE_READ_CHUNK_BYTES)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        break
                    log.write(chunk)
        else:
            while not stop_event.is_set():
                try:
                    chunk = pipe.read(_PIPE_READ_CHUNK_BYTES)
                except TypeError:
                    chunk = pipe.read()
                    if chunk:
                        log.write(
                            chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
                        )
                    break
                if not chunk:
                    break
                log.write(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    except (OSError, ValueError):
        pass
    finally:
        close_fn = getattr(pipe, "close", None)
        if callable(close_fn):
            with contextlib.suppress(OSError, ValueError):
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
    drain_grace_s: float = 0.5,
) -> BoundedSubprocessResult:
    """Run subprocess with process-tree isolation, pipe drains, and rotating logs."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_log = _BoundedRotatingLog(work_dir / f".{prefix}.stdout.log", max_bytes=max_log_bytes)
    err_log = _BoundedRotatingLog(work_dir / f".{prefix}.stderr.log", max_bytes=max_log_bytes)
    t_out: threading.Thread | None = None
    t_err: threading.Thread | None = None
    stop_drain = threading.Event()
    proc: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    spawn_epoch = time.time()
    reap_attempted = False

    try:
        proc = subprocess.Popen(  # noqa: S603
            list(cmd),
            **_popen_isolation_kwargs(),
        )
        raw_pid = getattr(proc, "pid", None)
        if os.name != "nt" and isinstance(raw_pid, int) and raw_pid > 0:
            pgid = raw_pid
        stdout_pipe = getattr(proc, "stdout", None)
        stderr_pipe = getattr(proc, "stderr", None)
        t_out = threading.Thread(
            target=_drain_pipe,
            args=(stdout_pipe, out_log, stop_drain),
            name=f"{prefix}-stdout-drain",
            daemon=True,
        )
        t_err = threading.Thread(
            target=_drain_pipe,
            args=(stderr_pipe, err_log, stop_drain),
            name=f"{prefix}-stderr-drain",
            daemon=True,
        )
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + float(timeout_s)
        while proc.poll() is None:
            if stop_token is not None and stop_token.stopped:
                _terminate_process_tree(
                    proc, pgid=pgid, created_after_epoch=spawn_epoch
                )
                reap_attempted = True
                raise LyraError(ErrorCode.PLAYBACK_ABORTED, cancel_message)
            if time.monotonic() > deadline:
                _terminate_process_tree(
                    proc, pgid=pgid, created_after_epoch=spawn_epoch
                )
                reap_attempted = True
                raise LyraError(timeout_code, timeout_message)
            time.sleep(0.05)

        _join_threads((t_out, t_err), drain_grace_s)

        # If a detached grandchild inherited pipes or stayed alive in the session/group,
        # reap the process tree so pipe EOF closes cleanly without hanging.
        if (
            t_out.is_alive()
            or t_err.is_alive()
            or (pgid is not None and _pgid_has_live_processes(pgid))
        ):
            _terminate_process_tree(
                proc, pgid=pgid, created_after_epoch=spawn_epoch, grace_s=0.4
            )
            reap_attempted = True
            _join_threads((t_out, t_err), 2.0)

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
            still_running = callable(getattr(proc, "poll", None)) and proc.poll() is None
            drainers_alive = (t_out is not None and t_out.is_alive()) or (
                t_err is not None and t_err.is_alive()
            )
            pg_alive = pgid is not None and _pgid_has_live_processes(pgid)
            if still_running or (not reap_attempted and (drainers_alive or pg_alive)):
                _safe_terminate_process_tree(
                    proc, pgid=pgid, created_after_epoch=spawn_epoch, grace_s=0.4
                )

        # Signal drain loops to exit before final join so POSIX selectors drainers
        # (and trickling pipes) exit promptly instead of leaking daemon threads.
        stop_drain.set()
        _join_threads((t_out, t_err), 1.5)
        out_log.close()
        err_log.close()

        if proc is not None:
            if (t_out is None or not t_out.is_alive()) and (
                stdout_obj := getattr(proc, "stdout", None)
            ) is not None:
                close_out = getattr(stdout_obj, "close", None)
                if callable(close_out):
                    with contextlib.suppress(OSError, ValueError):
                        close_out()
            if (t_err is None or not t_err.is_alive()) and (
                stderr_obj := getattr(proc, "stderr", None)
            ) is not None:
                close_err = getattr(stderr_obj, "close", None)
                if callable(close_err):
                    with contextlib.suppress(OSError, ValueError):
                        close_err()

        out_log.cleanup()
        err_log.cleanup()
