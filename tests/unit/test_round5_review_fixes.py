"""Round 5 independent Code Review regression tests (MCP, restore, logs, tags, LLM)."""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import wave
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lyraforge.agent.llm import (
    OpenAICompatibleLLMProvider,
    _coerce_float,
    _coerce_int,
    _coerce_opt_int,
)
from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import (
    LibraryStore,
    export_backup_zip,
    restore_backup_zip,
)
from lyraforge.mcp import LyraMCPServer, MCPTaskRegistry, MCPToolExecutor
from lyraforge.media.extract import extract_audio_to_wav
from lyraforge.media.subprocess_utils import (
    read_file_tail,
    run_bounded_subprocess,
)
from lyraforge.playback.guards import StopToken
from lyraforge.transcribers._subprocess import run_isolated_transcriber
from lyraforge.transcribers.base import (
    ModelInfo,
    TranscribeOptions,
    TranscriptionResult,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _write_pcm_wav(path: Path, *, duration_s: float = 0.25, rate: int = 22_050) -> None:
    n = int(rate * duration_s)
    frames = struct.pack("<" + "h" * n, *([2000 if (i % 50) < 25 else -2000 for i in range(n)]))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)


# ---------------------------------------------------------------------------
# 1. MCP unified protocol validation + bounded pool + race-free cancellation
# ---------------------------------------------------------------------------


def test_mcp_unified_validation_blocks_uninitialized_and_bad_args(tmp_path: Path) -> None:
    with LibraryStore(tmp_path / "lib") as store:
        executor = MCPToolExecutor(store)

        def _check_server_pair(raw_req: str, expected_code: int) -> None:
            srv_direct = LyraMCPServer(executor)
            res_direct = srv_direct.handle_message(raw_req)
            assert res_direct is not None
            assert res_direct["error"]["code"] == expected_code

            srv_stream = LyraMCPServer(executor)
            out = io.StringIO()
            srv_stream.serve_streams(io.StringIO(raw_req + "\n"), out)
            lines = [json.loads(ln) for ln in out.getvalue().splitlines() if ln.strip()]
            assert len(lines) == 1
            assert lines[0]["error"]["code"] == expected_code

        # Pre-initialization blocked on both handle_message & serve_streams
        _check_server_pair(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": {"query": "demo"}},
            }),
            -32002,
        )
        _check_server_pair(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}), -32002)

        # Malformed JSON-RPC requests
        for bad_raw, err_code in (
            ("{bad json", -32700),
            (json.dumps([1, 2, 3]), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": True, "method": "ping"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": 3, "method": 99}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping", "params": []}), -32602),
        ):
            _check_server_pair(bad_raw, err_code)

        # Post-initialize validation of tools/call name & arguments (never coerce non-dict)
        init_line = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        bad_calls = [
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": ""}},
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": 123}},
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": "not-an-object"},
            },
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": ["bad"]},
            },
            {
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": None},
            },
        ]
        stream_in = io.StringIO("\n".join([init_line, *[json.dumps(m) for m in bad_calls]]) + "\n")
        stream_out = io.StringIO()
        srv = LyraMCPServer(executor)
        srv.serve_streams(stream_in, stream_out)
        responses = {
            r["id"]: r for r in (json.loads(ln) for ln in stream_out.getvalue().splitlines())
        }
        assert responses[0]["result"]["protocolVersion"] == "2025-03-26"
        for cid in (10, 11, 12, 13, 14):
            assert responses[cid]["error"]["code"] == -32602

        # Same check via direct handle_message & direct executor.call
        srv2 = LyraMCPServer(executor)
        assert srv2.handle_message(init_line) is not None
        for call in bad_calls:
            resp = srv2.handle_message(json.dumps(call))
            assert resp is not None and resp["error"]["code"] == -32602
        bad_exec_res, is_err = executor.call("search_music", "bad")  # type: ignore[arg-type]
        assert is_err is True
        assert bad_exec_res["error"]["code"] == "INVALID_ARGUMENT"


def test_mcp_concurrency_queue_limits_cancellation_phases_and_disconnect(tmp_path: Path) -> None:
    midi_src = FIXTURE_DIR / "c_major_scale.mid"
    with LibraryStore(tmp_path / "lib") as store:
        imp = store.import_midi(midi_src, title="Concurrent Song")
        registry = MCPTaskRegistry(max_tasks=6)
        executor = MCPToolExecutor(store, tasks=registry)

        release_barrier = threading.Event()
        worker_entered = threading.Event()
        entered_count = 0
        entered_lock = threading.Lock()

        def slow_search(
            args: dict[str, Any],
            _req_id: str | int | None,
            _store: LibraryStore,
            stop_tok: StopToken | None,
        ) -> dict[str, Any]:
            nonlocal entered_count
            delay = float(args.get("_sleep", 0.0))
            if args.get("_explode"):
                raise RuntimeError("unexpected boom sk-secret-abc")
            with entered_lock:
                entered_count += 1
                if entered_count >= 2:
                    worker_entered.set()
            if delay > 0:
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline and not release_barrier.is_set():
                    if stop_tok is not None and stop_tok.stopped:
                        raise LyraError(ErrorCode.PLAYBACK_ABORTED, "aborted slow tool")
                    time.sleep(0.01)
            return {"ok": True, "echo": args.get("query"), "song_id": imp.song.id}

        executor._handlers["search_music"] = slow_search  # type: ignore[assignment]

        # 1. Parallel execution speedup & queue overload cap (-32001) + exception (-32603)
        srv = LyraMCPServer(executor, max_workers=2, max_pending=3, shutdown_timeout_s=3.0)
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            # 3 valid requests enter max_pending=3 queue (2 running, 1 waiting)
            json.dumps({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": {"query": "A", "_sleep": 0.25}},
            }),
            json.dumps({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": {"query": "B", "_sleep": 0.25}},
            }),
            # Request 12 waits in queue; pre-cancel id=12 before a worker starts it
            json.dumps({
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": {"query": "C", "_sleep": 0.05}},
            }),
            # Over capacity -> immediate -32001 without dropping accepted items
            json.dumps({
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "search_music", "arguments": {"query": "D"}},
            }),
            json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 12},
            }),
        ]
        t0 = time.monotonic()
        out = io.StringIO()
        srv.serve_streams(io.StringIO("\n".join(lines) + "\n"), out)
        elapsed = time.monotonic() - t0
        # 2 parallel 0.25s tasks must finish together well under sequential sum
        assert elapsed < 0.45
        by_id = {r["id"]: r for r in (json.loads(ln) for ln in out.getvalue().splitlines())}
        assert by_id[10]["result"]["structuredContent"]["echo"] == "A"
        assert by_id[11]["result"]["structuredContent"]["echo"] == "B"
        assert by_id[12]["result"]["isError"] is True
        assert by_id[12]["result"]["structuredContent"]["error"]["code"] == "PLAYBACK_ABORTED"
        assert by_id[13]["error"]["code"] == -32001
        assert srv._active_req_tokens == {}

        # 2. Unexpected exception in worker emits -32603 instead of silent loss;
        #    handler RuntimeError emits redacted structured tool error
        out_exc = io.StringIO()
        srv_exc = LyraMCPServer(executor, max_workers=2, max_pending=4)
        srv_exc.serve_streams(
            io.StringIO(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                + "\n"
                + json.dumps({
                    "jsonrpc": "2.0",
                    "id": 21,
                    "method": "tools/call",
                    "params": {"name": "search_music", "arguments": {"query": "X", "_explode": 1}},
                })
                + "\n"
            ),
            out_exc,
        )
        exc_resps = {r["id"]: r for r in (json.loads(ln) for ln in out_exc.getvalue().splitlines())}
        assert exc_resps[21]["result"]["isError"] is True
        assert exc_resps[21]["result"]["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

        orig_call = executor.call
        executor.call = lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom-outer"))  # type: ignore[method-assign]
        out_outer = io.StringIO()
        srv_outer = LyraMCPServer(executor, max_workers=2, max_pending=4)
        srv_outer.serve_streams(
            io.StringIO(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                + "\n"
                + json.dumps({
                    "jsonrpc": "2.0",
                    "id": 22,
                    "method": "tools/call",
                    "params": {"name": "search_music", "arguments": {"query": "X"}},
                })
                + "\n"
            ),
            out_outer,
        )
        executor.call = orig_call  # type: ignore[method-assign]
        outer_resps = {
            r["id"]: r for r in (json.loads(ln) for ln in out_outer.getvalue().splitlines())
        }
        assert outer_resps[22]["error"]["code"] == -32603

        # 3. Registry cancellation phases: before create(), during execution, after completion
        reg = MCPTaskRegistry(max_tasks=3)
        # Before task registration -> remembered and applied on create()
        assert reg.cancel("pre-1") is None
        rec_pre = reg.create("transcribe", task_id="pre-1", request_id=0)
        assert rec_pre.status == "cancelled"
        assert rec_pre.stop_token.stopped is True

        # During execution via requestId=0 (falsy int 0 must not be skipped)
        rec_zero = reg.create("transcribe", task_id="zero-task", request_id=0)
        assert reg.cancel("0") is rec_zero
        assert rec_zero.status == "cancelled"

        # After completion -> post-completion cancel must NOT overwrite status
        reg.create("transcribe", task_id="done-task", request_id=50)
        reg.finish("done-task", status="completed", progress=1.0)
        after = reg.cancel("50")
        assert after is not None and after.status == "completed"

        # 4. Stress test: concurrent normal arrange calls with zero SQLite errors or bad stdout
        stress_lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        ]
        for idx in range(2, 22):
            stress_lines.append(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "tools/call",
                    "params": {"name": "arrange", "arguments": {"song_id": imp.song.id}},
                })
            )
        stress_out = io.StringIO()
        srv_stress = LyraMCPServer(executor, max_workers=4, max_pending=24)
        srv_stress.serve_streams(io.StringIO("\n".join(stress_lines) + "\n"), stress_out)
        stress_resps = [json.loads(ln) for ln in stress_out.getvalue().splitlines()]
        assert len(stress_resps) == 21
        stress_errs = [
            r
            for r in stress_resps
            if r.get("id") != 1 and r.get("result", {}).get("isError") is not False
        ]
        assert not stress_errs, json.dumps(stress_errs, ensure_ascii=False)

        # 5a. Abrupt EOF disconnect while slow task is running -> cancels task cleanly on shutdown
        entered_long = threading.Event()
        stopped_flag = threading.Event()

        def long_wait(
            _args: dict[str, Any],
            _req_id: str | int | None,
            _store: LibraryStore,
            stop_tok: StopToken | None,
        ) -> dict[str, Any]:
            entered_long.set()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if stop_tok is not None and stop_tok.stopped:
                    stopped_flag.set()
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "disconnected")
                time.sleep(0.01)
            return {"ok": True}

        executor._handlers["search_music"] = long_wait  # type: ignore[assignment]
        srv_disc = LyraMCPServer(executor, max_workers=2, max_pending=4, shutdown_timeout_s=0.15)
        r_in, w_in = subprocess.os.pipe()
        out_disc = io.StringIO()
        srv_thread_exc: list[BaseException] = []

        def _run_disc_srv() -> None:
            try:
                with open(r_in, encoding="utf-8") as in_file:
                    srv_disc.serve_streams(in_file, out_disc)
            except BaseException as exc:  # pragma: no cover
                srv_thread_exc.append(exc)

        disc_th = threading.Thread(target=_run_disc_srv, daemon=True)
        disc_th.start()
        with open(w_in, "w", encoding="utf-8") as w_fh:
            w_fh.write(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                + "\n"
            )
            w_fh.write(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "search_music", "arguments": {}},
                })
                + "\n"
            )
            w_fh.flush()
            assert entered_long.wait(timeout=2.0)
        # Closing w_in sends immediate EOF -> shutdown_timeout cancels running long_wait
        disc_th.join(timeout=3.0)
        assert not disc_th.is_alive() and not srv_thread_exc
        assert stopped_flag.wait(timeout=2.0)

        # 5b. BrokenPipe on stdout triggers immediate disconnect shutdown
        class _ClosedStdout:
            def write(self, _data: str) -> int:
                raise BrokenPipeError("client gone")

            def flush(self) -> None:
                pass

        srv_bp = LyraMCPServer(executor, max_workers=2, max_pending=4, shutdown_timeout_s=0.15)
        bp_in = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        )
        assert srv_bp.serve_streams(bp_in, _ClosedStdout()) == 0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Library restore exclusive gate, stuck/active job drain & SQLite locking
# ---------------------------------------------------------------------------


def test_library_restore_exclusive_drain_stuck_job_wal_lock_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "live_data"
    wav_src = tmp_path / "song.wav"
    _write_pcm_wav(wav_src, duration_s=0.5)

    with LibraryStore(data_dir) as store:
        imp1 = store.import_audio(wav_src, title="Snapshot Song")
        song1_id = imp1.song.id
        backup_bytes = export_backup_zip(store)
        imp2 = store.import_midi(FIXTURE_DIR / "c_major_scale.mid", title="Extra Before Restore")
        extra_song_id = imp2.song.id

    token = "r5-token"
    headers = {SESSION_TOKEN_HEADER: token}
    app = create_app(data_dir=data_dir, session_token=token)
    app.state.restore_drain_timeout_s = 0.4

    class _ControllableTranscriber:
        def __init__(self, *, obey_cancel: bool) -> None:
            self.obey_cancel = obey_cancel
            self.started = threading.Event()
            self.release = threading.Event()

        def probe(self) -> ModelInfo:
            return ModelInfo(
                id="ctrl",
                display_name="Ctrl",
                available=True,
                license="MIT",
                scope_note="test",
            )

        def transcribe(
            self,
            _audio_path: Path,
            *,
            options: TranscribeOptions | None = None,
            on_progress: Any = None,
            stop_token: StopToken | None = None,
        ) -> TranscriptionResult:
            _ = options, on_progress
            self.started.set()
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and not self.release.is_set():
                if self.obey_cancel and stop_token is not None and stop_token.stopped:
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "cancelled")
                time.sleep(0.01)
            mid_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
            return TranscriptionResult(
                engine_id="ctrl",
                engine_version="1.0",
                midi_bytes=mid_bytes,
                note_count=8,
                duration_ms=1000,
            )

    # Case A: active cancellable transcription -> restore waits & cancels cleanly, blocks concurrent
    ctrl_ok = _ControllableTranscriber(obey_cancel=True)
    monkeypatch.setattr("lyraforge.api.job_service.get_transcriber", lambda _id: ctrl_ok)
    monkeypatch.setattr("lyraforge.library.store.get_transcriber", lambda _id: ctrl_ok)
    with TestClient(app) as client:
        sub = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song1_id, "engine_id": "builtin-mono", "async_mode": True},
        )
        assert sub.status_code == 200
        assert ctrl_ok.started.wait(timeout=2.0)

        rst = client.post(
            "/v1/library/restore",
            headers=headers,
            files={"file": ("bak.zip", backup_bytes, "application/zip")},
        )
        assert rst.status_code == 200
        assert rst.json()["restored"]["song_count"] == 1
        listed = client.get("/v1/library/songs", headers=headers).json()["songs"]
        assert [s["title"] for s in listed] == ["Snapshot Song"]

        # Normal writes work cleanly after restore
        imp3 = client.post(
            "/v1/imports",
            headers=headers,
            files={
                "file": (
                    "added.mid",
                    (FIXTURE_DIR / "c_major_scale.mid").read_bytes(),
                    "audio/midi",
                )
            },
        )
        assert imp3.status_code == 200
        assert len(client.get("/v1/library/songs", headers=headers).json()["songs"]) == 2

    # Case B: stuck job ignores cancellation -> restore rejects with 409 LIBRARY_BUSY, DB preserved
    ctrl_stuck = _ControllableTranscriber(obey_cancel=False)
    monkeypatch.setattr("lyraforge.api.job_service.get_transcriber", lambda _id: ctrl_stuck)
    monkeypatch.setattr("lyraforge.library.store.get_transcriber", lambda _id: ctrl_stuck)
    app_stuck = create_app(data_dir=data_dir, session_token=token)
    app_stuck.state.restore_drain_timeout_s = 0.15
    with TestClient(app_stuck) as client:
        sub_s = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song1_id, "engine_id": "builtin-mono", "async_mode": True},
        )
        assert sub_s.status_code == 200
        assert ctrl_stuck.started.wait(timeout=2.0)

        rst_fail = client.post(
            "/v1/library/restore",
            headers=headers,
            files={"file": ("bak.zip", backup_bytes, "application/zip")},
        )
        assert rst_fail.status_code == 409
        assert rst_fail.json()["error"]["code"] == "LIBRARY_BUSY"
        ctrl_stuck.release.set()

        # Service remains usable after rejected restore
        songs_after = client.get("/v1/library/songs", headers=headers)
        assert songs_after.status_code == 200
        assert len(songs_after.json()["songs"]) == 2

    # Case C: concurrent requests rejected with 409 LIBRARY_BUSY while restore holds gate
    from lyraforge.library import packaging as pkg_mod

    orig_restore = pkg_mod.restore_backup_zip
    in_restore = threading.Event()
    allow_finish = threading.Event()

    def slow_restore(target: str | Path, raw: bytes) -> dict[str, Any]:
        in_restore.set()
        assert allow_finish.wait(timeout=5.0)
        return orig_restore(target, raw)

    monkeypatch.setattr("lyraforge.api.app.restore_backup_zip", slow_restore)
    app_conc = create_app(data_dir=data_dir, session_token=token)
    with TestClient(app_conc) as client, ThreadPoolExecutor(max_workers=2) as tp:
        fut_rst = tp.submit(
            client.post,
            "/v1/library/restore",
            headers=headers,
            files={"file": ("bak.zip", backup_bytes, "application/zip")},
        )
        assert in_restore.wait(timeout=3.0)
        r_read = client.get("/v1/library/songs", headers=headers)
        r_job = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": song1_id, "engine_id": "builtin-mono", "async_mode": True},
        )
        assert r_read.status_code == 409 and r_read.json()["error"]["code"] == "LIBRARY_BUSY"
        assert r_job.status_code == 409 and r_job.json()["error"]["code"] == "LIBRARY_BUSY"
        allow_finish.set()
        assert fut_rst.result().status_code == 200
    monkeypatch.undo()

    # Case D: external active SQLite transaction locks DB -> rejected cleanly without modifying DB
    conn_ext = sqlite3.connect(data_dir / "library.db")
    try:
        conn_ext.execute("BEGIN")
        conn_ext.execute("SELECT COUNT(*) FROM songs").fetchall()
        with pytest.raises(LyraError) as busy_exc:
            restore_backup_zip(data_dir, backup_bytes)
        assert busy_exc.value.code == ErrorCode.LIBRARY_BUSY
    finally:
        conn_ext.close()

    # Case E: consecutive restores succeed & invalid extra song stays purged
    assert restore_backup_zip(data_dir, backup_bytes)["song_count"] == 1
    assert restore_backup_zip(data_dir, backup_bytes)["song_count"] == 1
    _ = extra_song_id

    # Case F: exception during restore rollback preserves old DB & restores service availability
    app_err = create_app(data_dir=data_dir, session_token=token)
    with TestClient(app_err) as client:
        imp_keep = client.post(
            "/v1/imports",
            headers=headers,
            files={
                "file": (
                    "keep.mid",
                    (FIXTURE_DIR / "chords_type1.mid").read_bytes(),
                    "audio/midi",
                )
            },
        )
        assert imp_keep.status_code == 200
        bad_zip = io.BytesIO()
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("library.db", b"corrupt")
            zf.writestr(
                "backup_manifest.json",
                json.dumps({"schema_version": 3, "kind": "lyraforge.backup"}),
            )
        r_bad = client.post(
            "/v1/library/restore",
            headers=headers,
            files={"file": ("bad.zip", bad_zip.getvalue(), "application/zip")},
        )
        assert r_bad.status_code == 400
        assert len(client.get("/v1/library/songs", headers=headers).json()["songs"]) == 2

    # Case G: lifespan shutdown waits for active restore gate before locking down service
    shutdown_order: list[str] = []
    app_shut = create_app(data_dir=data_dir, session_token=token)
    with app_shut.state.library_gate.exclusive("library_restore", wait_ops_timeout_s=2.0):
        shut_done = threading.Event()

        def _trigger_shutdown() -> None:
            app_shut.state.library_gate.begin_shutdown(wait_ops_timeout_s=2.0)
            shutdown_order.append("shutdown_done")
            shut_done.set()

        th = threading.Thread(target=_trigger_shutdown, daemon=True)
        th.start()
        time.sleep(0.08)
        assert not shut_done.is_set()
        shutdown_order.append("restore_done")
    assert shut_done.wait(timeout=2.0)
    assert shutdown_order == ["restore_done", "shutdown_done"]
    with pytest.raises(LyraError) as post_shut, app_shut.state.library_gate.use():
        pass
    assert post_shut.value.code == ErrorCode.LIBRARY_BUSY


# ---------------------------------------------------------------------------
# 3. Subprocess bounded log memory/disk, seek tail, cleanup & cancel/timeout
# ---------------------------------------------------------------------------


def test_subprocess_bounded_logs_seek_tail_cleanup_and_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Verify read_file_tail uses seek() rather than reading whole 2 MB file
    big_file = tmp_path / "big.log"
    big_file.write_bytes(b"A" * 1_500_000 + b"TAIL_MARKER_OK")
    tail = read_file_tail(big_file, max_bytes=64)
    assert tail.endswith(b"TAIL_MARKER_OK") and len(tail) == 64

    mid_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    flood_script = tmp_path / "flood.py"
    flood_script.write_text(
        f"""
import pathlib, sys, time
mode = sys.argv[1]
out_dir = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
chunk_o = b"OUT-" * 512
chunk_e = b"ERR-" * 512
if mode in ("ok", "fail"):
    for _ in range(180):
        sys.stdout.buffer.write(chunk_o)
        sys.stderr.buffer.write(chunk_e)
    sys.stdout.buffer.write(b"\\nSTDOUT_END\\n")
    sys.stderr.buffer.write(b"\\nSTDERR_END\\n")
    sys.stdout.flush()
    sys.stderr.flush()
    if mode == "ok" and out_dir is not None:
        (out_dir / "res.mid").write_bytes({mid_bytes!r})
        sys.exit(0)
    sys.exit(3)
else:
    time.sleep(5.0)
""",
        encoding="utf-8",
    )

    work = tmp_path / "sub_work"
    res = run_bounded_subprocess(
        [sys.executable, str(flood_script), "ok", str(tmp_path)],
        work_dir=work,
        prefix="flood-test",
        timeout_s=10.0,
        stop_token=None,
        cancel_message="cancelled",
        timeout_code=ErrorCode.TRANSCRIPTION_FAILED,
        timeout_message="timeout",
        max_log_bytes=16_384,
        tail_bytes=2048,
    )
    assert res.returncode == 0
    assert res.stdout_bytes > 300_000
    assert res.stderr_bytes > 300_000
    assert res.stdout_truncated is True and res.stderr_truncated is True
    assert res.peak_disk_bytes <= 16_384
    assert b"STDOUT_END" in res.stdout_tail and len(res.stdout_tail) <= 2048
    assert b"STDERR_END" in res.stderr_tail and len(res.stderr_tail) <= 2048
    assert list(work.glob("*")) == []  # All temp log & rotated .1 files cleaned up

    # Isolated transcriber failure retains tail diagnostic and never corrupts output MIDI
    fake_wav = tmp_path / "in.wav"
    _write_pcm_wav(fake_wav, duration_s=0.1)
    monkeypatch.setattr("lyraforge.media.subprocess_utils.MAX_SUBPROCESS_LOG_BYTES", 16_384)
    res_tr = run_isolated_transcriber(
        engine_id="flood-ok",
        display_name="Flood OK",
        runner=[sys.executable, str(flood_script)],
        missing_hint="missing",
        audio_path=fake_wav,
        build_cmd=lambda runner, _w, out_dir: [*runner, "ok", str(out_dir)],
    )
    assert res_tr.midi_bytes == mid_bytes

    with pytest.raises(LyraError) as fail_exc:
        run_isolated_transcriber(
            engine_id="flood-fail",
            display_name="Flood Fail",
            runner=[sys.executable, str(flood_script)],
            missing_hint="missing",
            audio_path=fake_wav,
            build_cmd=lambda runner, _w, out_dir: [*runner, "fail", str(out_dir)],
        )
    assert fail_exc.value.code == ErrorCode.TRANSCRIPTION_FAILED
    assert "STDERR_END" in fail_exc.value.message

    # Timeout & cancellation cleanup in extract_audio_to_wav
    hang_sh = tmp_path / "hang.py"
    hang_sh.write_text("import time; time.sleep(5)", encoding="utf-8")
    if sys.platform != "win32":
        wrap = tmp_path / "hang.sh"
        wrap.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{hang_sh}"\n', encoding="utf-8")
        wrap.chmod(0o755)
        dest_wav = tmp_path / "ff_out.wav"
        tok = StopToken()
        tok.request_stop("cancel")
        # Already cancelled before spawn -> immediate PLAYBACK_ABORTED
        with pytest.raises(LyraError) as c_exc:
            extract_audio_to_wav(fake_wav, dest_wav, stop_token=tok)
        assert c_exc.value.code == ErrorCode.PLAYBACK_ABORTED
        # Timeout kills hanging subprocess and leaves zero .log files behind
        mp3 = tmp_path / "dummy.mp3"
        mp3.write_bytes(b"mp3")
        with pytest.raises(LyraError) as t_exc:
            run_bounded_subprocess(
                [str(wrap)],
                work_dir=work,
                prefix="timeout-chk",
                timeout_s=0.12,
                stop_token=None,
                cancel_message="cancelled",
                timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
                timeout_message="timed out",
            )
        assert t_exc.value.code == ErrorCode.MEDIA_DECODE_FAILED
        assert list(work.glob("*")) == []


# ---------------------------------------------------------------------------
# 4. SQLite JSON1 exact tag search with LIKE/Unicode/LIMIT/join/scale
# ---------------------------------------------------------------------------


def test_sqlite_json1_exact_tag_search_unicode_escapes_and_pagination(tmp_path: Path) -> None:
    mid = FIXTURE_DIR / "c_major_scale.mid"
    with LibraryStore(tmp_path / "tag_db") as store:
        raw_base = mid.read_bytes()
        songs_meta = [
            ("Café Song", "Artist One", ["Café", "原神", "pop%20", "a_b", "x\\y"]),
            ("Sub Pop", "Artist Two", ["pop-rock", "classical"]),
            ("Solo Pop", "Artist Three", ["POP", "千本桜"]),
        ]
        # Import unique modified MIDI payloads so SHA deduplication treats each as distinct song
        created_ids: list[str] = []
        for idx, (title, artist, tags) in enumerate(songs_meta):
            p = tmp_path / f"song_{idx}.mid"
            p.write_bytes(raw_base + bytes([0xFF, 0x01, idx]))
            res = store.import_midi(p, title=title, artist=artist, tags=tags)
            created_ids.append(res.song.id)

        # Insert legacy ASCII-escaped JSON row directly to verify json_each backward compat
        store._conn.execute(
            "UPDATE songs SET tags_json = ? WHERE id = ?",
            (json.dumps(["原神", "LegacyTag"], ensure_ascii=True), created_ids[0]),
        )
        store._conn.commit()
        store.update_song_metadata(
            created_ids[0], tags=["Café", "原神", "pop%20", "a_b", "x\\y"]
        )

        # Exact tag matching respects Unicode case, %, _, backslash, and never matches pop-rock
        assert [s.title for s in store.search_songs(tag="café")] == ["Café Song"]
        assert [s.title for s in store.search_songs(tag="原神")] == ["Café Song"]
        assert [s.title for s in store.search_songs(tag="pop%20")] == ["Café Song"]
        assert [s.title for s in store.search_songs(tag="a_b")] == ["Café Song"]
        assert [s.title for s in store.search_songs(tag="x\\y")] == ["Café Song"]
        assert [s.title for s in store.search_songs(tag="pop")] == ["Solo Pop"]

        # Combined query (title/artist/tag) + tag + favorites_only + SQL LIMIT/OFFSET
        arr = store.arrange_song(created_ids[2])
        store.set_favorite(arr.id, True)
        assert [
            s.title
            for s in store.search_songs("Three", tag="pop", favorites_only=True, limit=1, offset=0)
        ] == ["Solo Pop"]

        # Pagination / scale check with 600 songs: LIMIT=1 still finds older exact match
        with store._conn:
            for i in range(600):
                store._conn.execute(
                    "INSERT INTO songs(id, title, artist, tags_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, '2026-11-23T00:00:00Z', '2026-11-23T00:00:00Z')",
                    (f"bulk-{i}", f"Bulk {i}", "Bulk", '["pop-rock"]'),
                )
        t0 = time.monotonic()
        exact_pop = store.search_songs(tag="pop", limit=1)
        assert (time.monotonic() - t0) < 0.5
        assert [s.title for s in exact_pop] == ["Solo Pop"]


# ---------------------------------------------------------------------------
# 5. LLM non-finite and invalid numeric parsing
# ---------------------------------------------------------------------------


def test_llm_numeric_coercion_rejects_nan_inf_extreme_and_non_numeric() -> None:
    bad_floats = (
        "nan",
        "NaN",
        "inf",
        "-inf",
        "+Infinity",
        "1e309",
        1e308,
        None,
        True,
        False,
        "abc",
        0.1,
        9.9,
    )
    for bad in bad_floats:
        assert _coerce_float(bad, 1.0, lo=0.25, hi=4.0) == 1.0
    assert _coerce_float(0.25, 1.0, lo=0.25, hi=4.0) == 0.25
    assert _coerce_float("4.0", 1.0, lo=0.25, hi=4.0) == 4.0
    assert _coerce_float(1.25, 1.0, lo=0.25, hi=4.0) == 1.25

    assert _coerce_int(float("inf"), 0, lo=-48, hi=48) == 0
    assert _coerce_int(float("nan"), 0, lo=-48, hi=48) == 0
    assert _coerce_int(True, 0, lo=-48, hi=48) == 0
    assert _coerce_opt_int(float("-inf"), 2, lo=-48, hi=48) == 2
    assert _coerce_opt_int("auto", 2, lo=-48, hi=48) is None

    class _FakeResp:
        def __init__(self, payload: bytes) -> None:
            self._bio = io.BytesIO(payload)

        def read(self, n: int = -1) -> bytes:
            return self._bio.read(n)

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    class _FakeOpener:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def open(self, *_a: Any, **_kw: Any) -> _FakeResp:
            return _FakeResp(self.payload)

    for bad_speed in ("nan", "inf", "-inf", 1e300, None, True, "fast"):
        body = json.dumps({
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "action": "arrange",
                            "query": "demo",
                            "speed": bad_speed,
                            "transpose": 999,
                            "arpeggiate_ms": -5,
                        })
                    }
                }
            ]
        }).encode("utf-8")
        prov = OpenAICompatibleLLMProvider(
            base_url="https://api.example.com/v1",
            api_key="k",
            model="m",
            opener=_FakeOpener(body),
        )
        intent = prov.parse_intent("帮我编曲")
        assert intent.speed == 1.0
        assert intent.transpose is None
        assert intent.arpeggiate_ms == 0
