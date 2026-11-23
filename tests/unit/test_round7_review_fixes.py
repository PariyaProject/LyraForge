"""Round 7 Code Review regression tests: concurrent preview cancel race & subprocess cleanup."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any

import pytest

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import LibraryStore
from lyraforge.library import store as store_mod
from lyraforge.media import subprocess_utils as su
from lyraforge.media.subprocess_utils import run_bounded_subprocess
from lyraforge.music_core.arranger import ArrangeOptions, Style
from lyraforge.playback.guards import StopToken

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _wav_sample_rate(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return wf.getframerate()


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        proc = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        return f'"{pid}"' in proc.stdout or f",{pid}," in proc.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_pid_dead(pid: int, *, timeout_s: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.04)
    return not _is_pid_alive(pid)


# ---------------------------------------------------------------------------
# 1. P2: Concurrent render_preview() cancel race & disk/DB state consistency
# ---------------------------------------------------------------------------


def test_render_preview_concurrent_cancel_preserves_shared_wav_and_db_consistency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "preview_lib"
    mid_src = FIXTURE_DIR / "c_major_scale.mid"
    with LibraryStore(data_dir) as s:
        imp = s.import_midi(mid_src, title="Concurrent Preview Song")
        arr = s.arrange_song(imp.song.id)

    expected_rel = f"songs/{imp.song.id}/previews/{arr.id}.wav"
    expected_wav = data_dir.resolve() / expected_rel

    # A. Concurrent Request A cancels right after synthesizing while Request B publishes first.
    orig_synth = store_mod.synthesize_performance_to_wav
    a_entered = threading.Event()
    b_published = threading.Event()
    tok_a = StopToken()

    def _raced_synth(
        doc: Any,
        out_path: str | Path,
        *,
        sample_rate: int = 22_050,
        is_cancelled: Any = None,
    ) -> Path:
        if is_cancelled is not None:
            a_entered.set()
            assert b_published.wait(timeout=5.0)
            res = orig_synth(
                doc, out_path, sample_rate=sample_rate, is_cancelled=is_cancelled
            )
            # Trigger stop right before publish stage in render_preview()
            tok_a.request_stop("cancel request A right before publish")
            return res
        return orig_synth(doc, out_path, sample_rate=sample_rate, is_cancelled=is_cancelled)

    monkeypatch.setattr(store_mod, "synthesize_performance_to_wav", _raced_synth)
    res_a: dict[str, Any] = {}

    def _run_req_a() -> None:
        with LibraryStore(data_dir) as sa:
            try:
                res_a["path"] = sa.render_preview(arr.id, stop_token=tok_a)
            except Exception as exc:  # noqa: BLE001
                res_a["error"] = exc

    th_a = threading.Thread(target=_run_req_a)
    th_a.start()
    assert a_entered.wait(timeout=5.0)

    with LibraryStore(data_dir) as sb:
        wav_b = sb.render_preview(arr.id)
        assert wav_b == expected_wav
        assert wav_b.is_file()
        b_bytes = wav_b.read_bytes()
    b_published.set()
    th_a.join(timeout=5.0)
    monkeypatch.undo()

    err_a = res_a.get("error")
    assert isinstance(err_a, LyraError)
    assert err_a.code == ErrorCode.PLAYBACK_ABORTED
    assert expected_wav.is_file()
    assert expected_wav.read_bytes() == b_bytes
    assert _wav_sample_rate(expected_wav) == 22_050
    assert list(expected_wav.parent.glob("*.tmp*")) == []
    with LibraryStore(data_dir) as check_s:
        assert check_s.get_arrangement(arr.id).preview_path == expected_rel

    # B. Fresh arrangement cancelled mid-render -> no shared WAV, preview_path stays None
    with LibraryStore(data_dir) as s2:
        arr2 = s2.arrange_song(
            imp.song.id,
            options=ArrangeOptions(style=Style.MELODY),
            label="Fresh For Cancel",
        )
        assert arr2.id != arr.id
    tok_b = StopToken()
    fresh_wav = data_dir.resolve() / f"songs/{imp.song.id}/previews/{arr2.id}.wav"

    def _cancel_synth(
        doc: Any,
        out_path: str | Path,
        *,
        sample_rate: int = 22_050,
        is_cancelled: Any = None,
    ) -> Path:
        res = orig_synth(doc, out_path, sample_rate=sample_rate, is_cancelled=None)
        tok_b.request_stop("cancel single request")
        return res

    monkeypatch.setattr(store_mod, "synthesize_performance_to_wav", _cancel_synth)
    with LibraryStore(data_dir) as s2, pytest.raises(LyraError) as exc_single:
        s2.render_preview(arr2.id, stop_token=tok_b)
    monkeypatch.undo()
    assert exc_single.value.code == ErrorCode.PLAYBACK_ABORTED
    assert not fresh_wav.exists()
    assert list(expected_wav.parent.glob("*.tmp*")) == []
    with LibraryStore(data_dir) as s2:
        assert s2.get_arrangement(arr2.id).preview_path is None

    # C. Exception during synthesis: neither leaks temp files nor damages prior WAV/DB
    def _boom_synth(*_a: Any, **_kw: Any) -> Path:
        Path(_a[1]).write_bytes(b"partial-temp")
        raise RuntimeError("simulated synthesizer failure")

    monkeypatch.setattr(store_mod, "synthesize_performance_to_wav", _boom_synth)
    with LibraryStore(data_dir) as s_err:
        with pytest.raises(RuntimeError, match="simulated synthesizer failure"):
            s_err.render_preview(arr2.id)
        assert not fresh_wav.exists()
        assert s_err.get_arrangement(arr2.id).preview_path is None

        with pytest.raises(RuntimeError, match="simulated synthesizer failure"):
            s_err.render_preview(arr.id)
        assert expected_wav.read_bytes() == b_bytes
        assert s_err.get_arrangement(arr.id).preview_path == expected_rel
    monkeypatch.undo()
    assert list(expected_wav.parent.glob("*.tmp*")) == []

    # D. Consecutive regenerations at different sample rates + trailing cancel
    with LibraryStore(data_dir) as s_seq:
        p1 = s_seq.render_preview(arr.id, sample_rate=16_000)
        assert _wav_sample_rate(p1) == 16_000
        p2 = s_seq.render_preview(arr.id, sample_rate=22_050)
        assert _wav_sample_rate(p2) == 22_050
        bytes_22k = p2.read_bytes()

    tok_d = StopToken()
    monkeypatch.setattr(
        store_mod,
        "synthesize_performance_to_wav",
        lambda d, out, sample_rate=8_000, is_cancelled=None: (
            orig_synth(d, out, sample_rate=sample_rate, is_cancelled=None),
            tok_d.request_stop("cancel 8k overwrite"),
        )[0],
    )
    with LibraryStore(data_dir) as s_seq, pytest.raises(LyraError) as exc_d:
        s_seq.render_preview(arr.id, sample_rate=8_000, stop_token=tok_d)
    monkeypatch.undo()
    assert exc_d.value.code == ErrorCode.PLAYBACK_ABORTED
    assert expected_wav.read_bytes() == bytes_22k
    assert _wav_sample_rate(expected_wav) == 22_050
    assert list(expected_wav.parent.glob("*.tmp*")) == []

    # E. Late cancellation AFTER atomic_replace_file succeeds still commits DB consistency
    orig_replace = store_mod.atomic_replace_file
    tok_e = StopToken()

    def _cancel_after_replace(src: Path, dst: Path) -> None:
        orig_replace(src, dst)
        tok_e.request_stop("late cancel after atomic publish")

    monkeypatch.setattr(store_mod, "atomic_replace_file", _cancel_after_replace)
    with LibraryStore(data_dir) as s_late:
        out_e = s_late.render_preview(arr2.id, sample_rate=16_000, stop_token=tok_e)
        assert out_e == fresh_wav
        assert fresh_wav.is_file() and _wav_sample_rate(fresh_wav) == 16_000
        assert (
            s_late.get_arrangement(arr2.id).preview_path
            == f"songs/{imp.song.id}/previews/{arr2.id}.wav"
        )
    monkeypatch.undo()
    assert list(expected_wav.parent.glob("*.tmp*")) == []


# ---------------------------------------------------------------------------
# 2. P2: Subprocess drain thread lifecycle, reap failure fallback & log cleanup
# ---------------------------------------------------------------------------


def test_subprocess_utils_reap_failure_detached_pipe_holder_and_log_cleanup_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _prefix_drainers(prefix: str) -> list[str]:
        return [
            th.name
            for th in threading.enumerate()
            if th.is_alive() and th.name.startswith(f"{prefix}-") and th.name.endswith("-drain")
        ]

    raw_base_py = getattr(sys, "_base_executable", sys.executable)
    direct_py = raw_base_py if raw_base_py and Path(raw_base_py).is_file() else sys.executable

    # A. Simulated _terminate_process_tree failure must still reap child via fallback & clean logs
    work_a = tmp_path / "work_reap_err"
    child_pid_file = tmp_path / "reap_err_pid.txt"
    sleep_script = (
        f"import os, pathlib, time; "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
        f"time.sleep(30)"
    )

    def _broken_reap(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("simulated reap error")

    monkeypatch.setattr(su, "_terminate_process_tree", _broken_reap)
    with pytest.raises(RuntimeError, match="simulated reap error"):
        run_bounded_subprocess(
            [direct_py, "-c", sleep_script],
            work_dir=work_a,
            prefix="r7-reaperr",
            timeout_s=0.25,
            stop_token=None,
            cancel_message="cancelled",
            timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
            timeout_message="timed out",
        )
    monkeypatch.undo()
    assert child_pid_file.is_file()
    reaped_pid = int(child_pid_file.read_text(encoding="utf-8"))
    assert _wait_pid_dead(reaped_pid, timeout_s=5.0)
    assert list(work_a.glob("*")) == []
    assert not _prefix_drainers("r7-reaperr")

    # B. Worst-case stuck pipe blocked past join deadline -> zero log cleanup vs thread write race
    work_b = tmp_path / "work_stuck_pipe"
    release_pipe = threading.Event()
    pipe_closed_late = threading.Event()

    class _StuckStdoutPipe:
        def __init__(self) -> None:
            self._calls = 0

        def read(self, _n: int = 4096) -> bytes:
            self._calls += 1
            if self._calls == 1:
                return b"FIRST_CHUNK\n"
            if self._calls == 2:
                assert release_pipe.wait(timeout=5.0)
                return b"LATE_CHUNK_AFTER_CLEANUP\n"
            return b""

        def close(self) -> None:
            pipe_closed_late.set()

    class _StubProc:
        def __init__(self) -> None:
            self.pid = -1
            self.returncode = 0
            self.stdout = _StuckStdoutPipe()
            self.stderr = None

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(su.subprocess, "Popen", lambda *_a, **_kw: _StubProc())
    res_b = run_bounded_subprocess(
        ["stub-cmd"],
        work_dir=work_b,
        prefix="r7-stuck",
        timeout_s=5.0,
        stop_token=None,
        cancel_message="cancelled",
        timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
        timeout_message="timed out",
        drain_grace_s=0.05,
    )
    monkeypatch.undo()
    assert res_b.returncode == 0
    assert b"FIRST_CHUNK" in res_b.stdout_tail
    assert list(work_b.glob("*")) == []

    # Release stuck pipe AFTER cleanup() finished; late write is safely ignored and zero files exist
    release_pipe.set()
    assert pipe_closed_late.wait(timeout=3.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _prefix_drainers("r7-stuck"):
        time.sleep(0.02)
    assert not _prefix_drainers("r7-stuck")
    assert list(work_b.glob("*")) == []

    # C. POSIX: detached start_new_session=True grandchild holding stdout pipe while parent exits 0
    if os.name != "nt":
        work_c = tmp_path / "work_detached_posix"
        detached_pid_file = tmp_path / "detached_pid.txt"
        detached_script = "\n".join([
            "import pathlib, subprocess, sys",
            f"p = pathlib.Path({str(detached_pid_file)!r})",
            "child = subprocess.Popen(",
            "    [sys.executable, '-c', 'import time; time.sleep(4.0)'],",
            "    start_new_session=True,",
            ")",
            "p.write_text(str(child.pid), encoding='utf-8')",
            "sys.stdout.buffer.write(b'PARENT_EXITED_DETACHED\\n')",
            "sys.stdout.buffer.flush()",
        ])
        t0 = time.monotonic()
        try:
            res_c = run_bounded_subprocess(
                [sys.executable, "-c", detached_script],
                work_dir=work_c,
                prefix="r7-detach",
                timeout_s=5.0,
                stop_token=None,
                cancel_message="cancelled",
                timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
                timeout_message="timed out",
                drain_grace_s=0.15,
            )
            elapsed_c = time.monotonic() - t0
            assert elapsed_c < 3.5
            assert res_c.returncode == 0
            assert b"PARENT_EXITED_DETACHED" in res_c.stdout_tail
            assert list(work_c.glob("*")) == []
            assert not _prefix_drainers("r7-detach")
        finally:
            if detached_pid_file.is_file():
                dpid = int(detached_pid_file.read_text(encoding="utf-8"))
                with contextlib.suppress(OSError):
                    os.kill(dpid, signal.SIGKILL)

    # D. Normal fast stdout/stderr + log rotation integrity (protects FFmpeg / transcriber paths)
    work_d = tmp_path / "work_normal"
    normal_script = (
        "import sys; "
        "sys.stdout.buffer.write(b'HEAD-' * 400 + b'TAIL_OUT\\n'); "
        "sys.stderr.buffer.write(b'WARN-' * 400 + b'TAIL_ERR\\n'); "
        "sys.stdout.buffer.flush(); sys.stderr.buffer.flush()"
    )
    res_d = run_bounded_subprocess(
        [sys.executable, "-c", normal_script],
        work_dir=work_d,
        prefix="r7-normal",
        timeout_s=10.0,
        stop_token=None,
        cancel_message="cancelled",
        timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
        timeout_message="timed out",
        max_log_bytes=2048,
        tail_bytes=256,
    )
    assert res_d.returncode == 0
    assert res_d.stdout_truncated is True
    assert res_d.stderr_truncated is True
    assert b"TAIL_OUT" in res_d.stdout_tail
    assert b"TAIL_ERR" in res_d.stderr_tail
    assert res_d.peak_disk_bytes <= 2048
    assert list(work_d.glob("*")) == []
    assert not _prefix_drainers("r7-normal")
