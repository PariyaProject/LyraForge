"""Round 6 Code Review regression tests: restore rollback, eviction, MCP cancel, process tree."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import (
    LibraryStore,
    export_backup_zip,
    recover_interrupted_restore,
    restore_backup_zip,
)
from lyraforge.library import packaging as pkg_mod
from lyraforge.mcp import LyraMCPServer, MCPTaskRegistry, MCPToolExecutor
from lyraforge.media.subprocess_utils import run_bounded_subprocess
from lyraforge.music_core import arranger as arranger_mod
from lyraforge.playback.guards import StopToken
from lyraforge.preview import synth as synth_mod
from lyraforge.sources.base import SourceCandidate
from lyraforge.sources.url import DirectUrlSourceAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"
_TRANSIENT_SIDECARS = frozenset({"library.db-wal", "library.db-shm", "library.db-journal"})


def _tree_hashes(root: Path, *, include_db: bool = True) -> dict[str, str]:
    """Snapshot relative file hashes under a library root (ignoring transient WAL sidecars)."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(root).as_posix()
        if rel in _TRANSIENT_SIDECARS:
            continue
        if not include_db and rel == "library.db":
            continue
        out[rel] = hashlib.sha256(item.read_bytes()).hexdigest()
    return out


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
# 1. P1: Transactional library restore, locks, rollback preservation, recovery
# ---------------------------------------------------------------------------


def test_restore_preserves_original_library_across_locks_failures_and_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap_dir = tmp_path / "snap_src"
    live_dir = tmp_path / "live_lib"
    mid_c = FIXTURE_DIR / "c_major_scale.mid"
    mid_chords = FIXTURE_DIR / "chords_type1.mid"

    with LibraryStore(snap_dir) as s_store:
        imp_snap = s_store.import_midi(mid_c, title="Backup Snapshot Song")
        s_store.arrange_song(imp_snap.song.id)
        backup_v1 = export_backup_zip(s_store)

    with LibraryStore(live_dir) as l_store:
        imp_live = l_store.import_midi(mid_chords, title="Original Live Song")
        arr_live = l_store.arrange_song(imp_live.song.id)
        l_store.render_preview(arr_live.id)
        l_store.set_setting("default_style", "rich")
        # Quiesce DB to a deterministic single-file baseline for exact hash checks
        l_store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _db_logical_snapshot(root: Path) -> dict[str, list[tuple[Any, ...]]]:
        conn = sqlite3.connect(root / "library.db")
        try:
            return {
                tbl: conn.execute(f"SELECT * FROM {tbl} ORDER BY rowid").fetchall()  # noqa: S608
                for tbl in ("songs", "sources", "arrangements", "settings")
            }
        finally:
            conn.close()

    baseline_non_db = _tree_hashes(live_dir, include_db=False)
    baseline_db_rows = _db_logical_snapshot(live_dir)
    assert any(k.endswith(".mid") for k in baseline_non_db)

    def _assert_live_intact() -> None:
        assert _tree_hashes(live_dir, include_db=False) == baseline_non_db
        assert _db_logical_snapshot(live_dir) == baseline_db_rows
        with LibraryStore(live_dir) as check_store:
            songs = check_store.search_songs("")
            assert [s.title for s in songs] == ["Original Live Song"]
            assert check_store.get_settings()["default_style"] == "rich"

    # A. External open DB transaction -> rejected cleanly before mutation
    pre_a_hashes = _tree_hashes(live_dir)
    conn_lock = sqlite3.connect(live_dir / "library.db")
    try:
        conn_lock.execute("BEGIN")
        conn_lock.execute("SELECT COUNT(*) FROM songs").fetchall()
        with pytest.raises(LyraError) as exc_db:
            restore_backup_zip(live_dir, backup_v1)
        assert exc_db.value.code == ErrorCode.LIBRARY_BUSY
    finally:
        conn_lock.close()
    assert _tree_hashes(live_dir) == pre_a_hashes
    _assert_live_intact()

    # B. Read-only / locked file inside original library -> rejected before even touching DB header
    locked_file = next(
        live_dir / rel for rel in sorted(baseline_non_db) if rel.endswith(".json")
    )
    pre_b_hashes = _tree_hashes(live_dir)
    orig_mode = locked_file.stat().st_mode
    locked_file.chmod(stat.S_IREAD)
    try:
        with pytest.raises(LyraError) as exc_ro:
            restore_backup_zip(live_dir, backup_v1)
        assert exc_ro.value.code == ErrorCode.LIBRARY_BUSY
    finally:
        locked_file.chmod(orig_mode | stat.S_IWRITE)
    assert _tree_hashes(live_dir) == pre_b_hashes
    _assert_live_intact()

    # C. PermissionError raised during _copy_dir_contents -> LIBRARY_BUSY, original intact
    orig_copy = pkg_mod._copy_dir_contents
    copy_calls = 0

    def _copy_perm_err(src: Path, dst: Path, **kw: Any) -> int:
        nonlocal copy_calls
        copy_calls += 1
        if copy_calls == 2:
            raise PermissionError("simulated persistent file handle lock")
        return orig_copy(src, dst, **kw)

    monkeypatch.setattr(pkg_mod, "_copy_dir_contents", _copy_perm_err)
    with pytest.raises(LyraError) as exc_perm:
        restore_backup_zip(live_dir, backup_v1)
    assert exc_perm.value.code == ErrorCode.LIBRARY_BUSY
    monkeypatch.undo()
    _assert_live_intact()

    # D1. First directory rename (target -> displaced) fails -> original untouched
    orig_rename = pkg_mod._rename_dir_with_retry
    rename_calls = 0

    def _fail_first_rename(src: Path, dst: Path, **kw: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 1:
            raise PermissionError("locked root handle")
        orig_rename(src, dst, **kw)

    monkeypatch.setattr(pkg_mod, "_rename_dir_with_retry", _fail_first_rename)
    with pytest.raises(LyraError) as exc_r1:
        restore_backup_zip(live_dir, backup_v1)
    assert exc_r1.value.code == ErrorCode.LIBRARY_BUSY
    monkeypatch.undo()
    _assert_live_intact()

    # D2. Second directory rename (prepared -> target) fails after first rename succeeded
    rename_calls = 0

    def _fail_second_rename(src: Path, dst: Path, **kw: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated atomic swap failure")
        orig_rename(src, dst, **kw)

    monkeypatch.setattr(pkg_mod, "_rename_dir_with_retry", _fail_second_rename)
    with pytest.raises(OSError, match="simulated atomic swap failure"):
        restore_backup_zip(live_dir, backup_v1)
    monkeypatch.undo()
    _assert_live_intact()

    # E. Rollback itself fails (post-swap validation fails AND rollback rename throws) ->
    #    must NOT report success, must preserve intact snapshot on disk + manual recovery guidance
    orig_verify = pkg_mod._verify_sqlite_backup
    verify_calls = 0

    def _fail_post_swap_verify(db_path: Path) -> None:
        nonlocal verify_calls
        verify_calls += 1
        if db_path.parent == live_dir.resolve() and verify_calls == 3:
            raise OSError("post-swap validation interrupted")
        orig_verify(db_path)

    rename_calls = 0

    def _fail_rollback_rename(src: Path, dst: Path, **kw: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        # Calls 1 & 2 perform swap; call 3 is rollback moving target -> failed_dir
        if rename_calls == 3:
            raise PermissionError("persistent lock blocking rollback")
        orig_rename(src, dst, **kw)

    monkeypatch.setattr(pkg_mod, "_verify_sqlite_backup", _fail_post_swap_verify)
    monkeypatch.setattr(pkg_mod, "_rename_dir_with_retry", _fail_rollback_rename)
    with pytest.raises(LyraError) as exc_double:
        restore_backup_zip(live_dir, backup_v1)
    monkeypatch.undo()
    assert exc_double.value.code == ErrorCode.LIBRARY_BUSY
    assert exc_double.value.details["rollback_failed"] is True
    assert exc_double.value.details["manual_recovery_steps"]
    snap_dir_str = (
        exc_double.value.details["displaced_dir"] or exc_double.value.details["rollback_dir"]
    )
    assert snap_dir_str is not None
    preserved_snap = Path(snap_dir_str)
    assert preserved_snap.is_dir()
    assert _tree_hashes(preserved_snap, include_db=False) == baseline_non_db

    # Once external lock clears, recover_interrupted_restore recovers original DB automatically
    recovered = recover_interrupted_restore(live_dir)
    assert recovered is not None and recovered["recovered"] is True
    _assert_live_intact()
    assert not preserved_snap.exists()

    # F1. Mid-restore KeyboardInterrupt (BaseException) -> automatic rollback preserves original
    verify_calls = 0

    def _interrupt_post_swap(db_path: Path) -> None:
        nonlocal verify_calls
        verify_calls += 1
        if db_path.parent == live_dir.resolve() and verify_calls == 3:
            raise KeyboardInterrupt("simulated SIGINT mid-restore")
        orig_verify(db_path)

    monkeypatch.setattr(pkg_mod, "_verify_sqlite_backup", _interrupt_post_swap)
    with pytest.raises(KeyboardInterrupt):
        restore_backup_zip(live_dir, backup_v1)
    monkeypatch.undo()
    _assert_live_intact()

    # F2. Simulated hard crash mid-swap (.restore-txn.json + displaced_dir left) ->
    #     opening LibraryStore automatically recovers original library
    crashed_displaced = tmp_path / ".live_lib.displaced-crash99"
    shutil.move(str(live_dir), str(crashed_displaced))
    txn_path = tmp_path / ".live_lib.restore-txn.json"
    txn_path.write_text(
        json.dumps({
            "phase": "swapping",
            "target_dir": str(live_dir.resolve()),
            "displaced_dir": str(crashed_displaced.resolve()),
        }),
        encoding="utf-8",
    )
    assert not live_dir.exists()
    with LibraryStore(live_dir) as recovered_store:
        assert [s.title for s in recovered_store.search_songs("")] == ["Original Live Song"]
    assert not txn_path.exists()
    assert not crashed_displaced.exists()

    # G. Restore + concurrent task submission & DB reads via API
    token = "r6-tok"
    headers = {SESSION_TOKEN_HEADER: token}
    app = create_app(data_dir=live_dir, session_token=token)
    in_restore = threading.Event()
    allow_finish = threading.Event()
    real_restore = pkg_mod.restore_backup_zip

    def _gated_restore(target: str | Path, raw: bytes) -> dict[str, Any]:
        in_restore.set()
        assert allow_finish.wait(timeout=5.0)
        return real_restore(target, raw)

    monkeypatch.setattr("lyraforge.api.app.restore_backup_zip", _gated_restore)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        fut = pool.submit(
            client.post,
            "/v1/library/restore",
            headers=headers,
            files={"file": ("bak.zip", backup_v1, "application/zip")},
        )
        assert in_restore.wait(timeout=3.0)
        r_songs = client.get("/v1/library/songs", headers=headers)
        r_submit = client.post(
            "/v1/jobs/transcribe",
            headers=headers,
            json={"song_id": imp_live.song.id, "engine_id": "builtin-mono", "async_mode": True},
        )
        assert r_songs.status_code == 409 and r_songs.json()["error"]["code"] == "LIBRARY_BUSY"
        assert r_submit.status_code == 409 and r_submit.json()["error"]["code"] == "LIBRARY_BUSY"
        allow_finish.set()
        r_done = fut.result()
        assert r_done.status_code == 200
        restored_titles = [
            s["title"] for s in client.get("/v1/library/songs", headers=headers).json()["songs"]
        ]
        assert restored_titles == ["Backup Snapshot Song"]
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# 2. P2: MCPTaskRegistry never evicts active/running tasks
# ---------------------------------------------------------------------------


def test_mcp_task_registry_never_evicts_active_tasks_and_enforces_capacity(
    tmp_path: Path,
) -> None:
    # A. max_tasks=1: creating 2nd active task rejects with LIMIT_EXCEEDED without losing 1st
    reg1 = MCPTaskRegistry(max_tasks=1)
    r1 = reg1.create("arrange", task_id="active-1", request_id="req-1")
    with pytest.raises(LyraError) as cap_exc:
        reg1.create("preview", task_id="active-2", request_id="req-2")
    assert cap_exc.value.code == ErrorCode.LIMIT_EXCEEDED
    assert reg1.get("active-1") is r1
    assert reg1.active_count() == 1
    assert reg1.get("active-2") is None

    # Cancel sets stop_token + status, but keeps record non-evictable until worker finishes!
    assert reg1.cancel("req-1") is r1
    assert r1.stop_token.stopped is True
    assert not r1.finished
    with pytest.raises(LyraError) as cap_unwound:
        reg1.create("preview", task_id="active-2", request_id="req-2")
    assert cap_unwound.value.code == ErrorCode.LIMIT_EXCEEDED

    # Once worker calls finish(), cancelled slot is safely reclaimed by next task
    reg1.finish("active-1", status="cancelled")
    assert r1.finished is True
    r2 = reg1.create("preview", task_id="active-2", request_id="req-2")
    assert reg1.get("active-1") is None
    assert reg1.get("active-2") is r2
    # Stale request mapping from reclaimed active-1 was cleaned up (adds to _pre_cancelled cleanly)
    assert reg1.cancel("req-1") is None
    reg1.consume_pre_cancel("req-1")

    # B. Multi-task max_tasks=3 + get_task_status works while registry is full
    with LibraryStore(tmp_path / "lib") as store:
        reg3 = MCPTaskRegistry(max_tasks=3)
        executor = MCPToolExecutor(store, tasks=reg3)
        t_a = reg3.create("transcribe", task_id="ta", request_id=10)
        t_b = reg3.create("arrange", task_id="tb", request_id=11)
        t_c = reg3.create("preview", task_id="tc", request_id=12)

        # Frequent polling while capacity full always succeeds cleanly
        for _ in range(5):
            snap, is_err = executor.call("get_task_status", {"task_id": "ta"})
            assert is_err is False
            assert snap["task"]["task_id"] == "ta"
            assert snap["task"]["status"] == "running"

        # Exceeding active capacity returns recoverable LIMIT_EXCEEDED via MCPToolExecutor
        cap_payload, cap_err = executor.call("search_music", {"query": "anything"})
        assert cap_err is True
        assert cap_payload["error"]["code"] == "LIMIT_EXCEEDED"
        assert cap_payload["error"]["recoverable"] is True

        # Finishing one active task unlocks creation of t_d while t_a & t_c stay intact
        reg3.finish(t_b.task_id, status="completed", progress=1.0)
        t_d = reg3.create("export_score", task_id="td", request_id=13)
        assert reg3.get(t_a.task_id) is t_a
        assert reg3.get(t_c.task_id) is t_c
        assert reg3.get(t_d.task_id) is t_d
        assert reg3.get(t_b.task_id) is None

    # C. High-concurrency stress: every running task stays locatable & cancellable
    stress_reg = MCPTaskRegistry(max_tasks=4)
    active_lock = threading.Lock()
    active_ids: set[str] = set()
    evicted_active: list[str] = []

    def _worker(idx: int) -> None:
        tid = f"stress-{idx}"
        while True:
            try:
                rec = stress_reg.create("arrange", task_id=tid, request_id=f"sreq-{idx}")
                break
            except LyraError as exc:
                assert exc.code == ErrorCode.LIMIT_EXCEEDED
                time.sleep(0.005)
        with active_lock:
            active_ids.add(tid)
        time.sleep(0.02)
        if stress_reg.get(tid) is None:
            with active_lock:
                evicted_active.append(tid)
        # Exercise cancel on odd workers and normal completion on even workers
        if idx % 2 == 1:
            assert stress_reg.cancel(f"sreq-{idx}") is rec
            stress_reg.finish(tid, status="cancelled")
        else:
            stress_reg.finish(tid, status="completed", progress=1.0)
        with active_lock:
            active_ids.discard(tid)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(_worker, i) for i in range(28)]
        for f in futs:
            f.result()
    assert not evicted_active
    assert stress_reg.active_count() == 0


# ---------------------------------------------------------------------------
# 3. P2: Cooperative cancellation across MCP tools & commit/rollback boundaries
# ---------------------------------------------------------------------------


def test_mcp_tools_cooperative_cancellation_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    midi_src = FIXTURE_DIR / "chords_type1.mid"

    with LibraryStore(tmp_path / "mcp_cancel_lib") as store:
        imp = store.import_midi(midi_src, title="Cancel Target Song", artist="Tester")
        arr = store.arrange_song(imp.song.id)

        registry = MCPTaskRegistry(max_tasks=50)
        executor = MCPToolExecutor(store, tasks=registry)

        # A. Pre-execution cancel (via request_id) across non-transcribe tools
        pre_tools = [
            ("search_music", {"query": "Cancel Target"}),
            ("import_media", {"path": str(FIXTURE_DIR / "c_major_scale.mid")}),
            ("arrange", {"song_id": imp.song.id, "style": "rich"}),
            ("preview", {"arrangement_id": arr.id}),
            ("save_to_library", {"song_id": imp.song.id, "title": "Should Not Apply"}),
            (
                "export_score",
                {
                    "arrangement_id": arr.id,
                    "format": "midi",
                    "output_path": str(tmp_path / "pre_should_not_exist.mid"),
                },
            ),
        ]
        for idx, (tname, targs) in enumerate(pre_tools, start=500):
            assert registry.cancel(str(idx)) is None
            payload, is_err = executor.call(tname, targs, request_id=idx)
            assert is_err is True
            assert payload["error"]["code"] == "PLAYBACK_ABORTED"
        assert store.get_song(imp.song.id).song.title == "Cancel Target Song"
        assert len(store.search_songs("")) == 1
        assert not (tmp_path / "pre_should_not_exist.mid").exists()

        # B1. Mid-execution cancel in import_media (chunked URL download loop)
        class _ChunkedResponse:
            def __init__(self, on_first_chunk: threading.Event, stop_evt: threading.Event) -> None:
                self._n = 0
                self._on_first = on_first_chunk
                self._stop_evt = stop_evt

            def read(self, _n: int = 65536) -> bytes:
                self._n += 1
                if self._n == 1:
                    self._on_first.set()
                    return midi_src.read_bytes()[:12]
                assert self._stop_evt.wait(timeout=3.0)
                return midi_src.read_bytes()[12:]

            def __enter__(self) -> _ChunkedResponse:
                return self

            def __exit__(self, *_a: object) -> None:
                return None

        dl_started = threading.Event()
        dl_release = threading.Event()

        class _ChunkedOpener:
            def open(self, *_a: Any, **_kw: Any) -> _ChunkedResponse:
                return _ChunkedResponse(dl_started, dl_release)

        url_exec = MCPToolExecutor(
            store,
            tasks=MCPTaskRegistry(max_tasks=20),
            url_adapter=DirectUrlSourceAdapter(opener=_ChunkedOpener()),
        )
        tok_dl = StopToken()
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut_dl = pool.submit(
                url_exec.call,
                "import_media",
                {
                    "url": "https://93.184.216.34/c_major_scale.mid",
                    "allow_network": True,
                    "task_id": "dl-mid",
                },
                request_id=601,
                stop_token=tok_dl,
            )
            assert dl_started.wait(timeout=3.0)
            url_exec.tasks.cancel("dl-mid")
            dl_release.set()
            res_dl, err_dl = fut_dl.result(timeout=5.0)
        assert err_dl is True
        assert res_dl["error"]["code"] == "PLAYBACK_ABORTED"
        assert url_exec.tasks.get("dl-mid") is not None
        assert url_exec.tasks.get("dl-mid").status == "cancelled"  # type: ignore[union-attr]
        assert len(store.search_songs("")) == 1

        # B2. Mid-execution cancel in arrange (inside transpose search)
        orig_cost = arranger_mod._transpose_cost
        tok_arr = StopToken()

        def _cancelling_cost(*a: Any, **kw: Any) -> int:
            tok_arr.request_stop("cancel mid-arrange")
            return orig_cost(*a, **kw)

        monkeypatch.setattr(arranger_mod, "_transpose_cost", _cancelling_cost)
        res_arr, err_arr = executor.call(
            "arrange",
            {"song_id": imp.song.id, "style": "rich", "task_id": "arr-mid"},
            request_id=602,
            stop_token=tok_arr,
        )
        monkeypatch.undo()
        assert err_arr is True and res_arr["error"]["code"] == "PLAYBACK_ABORTED"
        assert len(store.get_song(imp.song.id).arrangements) == 1
        assert registry.get("arr-mid").status == "cancelled"  # type: ignore[union-attr]

        # B3. Mid-execution cancel in preview (inside note rendering loop)
        orig_render = synth_mod._render_note
        tok_prv = StopToken()

        def _cancelling_note(*a: Any, **kw: Any) -> None:
            tok_prv.request_stop("cancel mid-preview")
            orig_render(*a, **kw)

        monkeypatch.setattr(synth_mod, "_render_note", _cancelling_note)
        prv_out = tmp_path / "cancelled_preview.wav"
        res_prv, err_prv = executor.call(
            "preview",
            {"arrangement_id": arr.id, "output_path": str(prv_out), "task_id": "prv-mid"},
            request_id=603,
            stop_token=tok_prv,
        )
        monkeypatch.undo()
        assert err_prv is True and res_prv["error"]["code"] == "PLAYBACK_ABORTED"
        assert not prv_out.exists()
        assert store.get_arrangement(arr.id).preview_path is None
        assert registry.get("prv-mid").status == "cancelled"  # type: ignore[union-attr]

        # B4. Mid-execution cancel in search_music (cancels between online catalog items)
        tok_srch = StopToken()
        online_calls = 0

        class _SlowOnline:
            def search(
                self,
                query: str,
                *,
                limit: int = 10,
                is_cancelled: Any = None,
            ) -> list[SourceCandidate]:
                nonlocal online_calls
                online_calls += 1
                tok_srch.request_stop("cancel during online search")
                if is_cancelled is not None and is_cancelled():
                    raise LyraError(ErrorCode.PLAYBACK_ABORTED, "online cancelled")
                return [
                    SourceCandidate(
                        source_type="archive.org",
                        id="x/y.mid",
                        title=query,
                        artist="A",
                        format="midi",
                        location="https://93.184.216.34/y.mid",
                        license_note="CC0",
                        requires_authorization=True,
                    )
                ][:limit]

        srch_exec = MCPToolExecutor(
            store,
            tasks=MCPTaskRegistry(max_tasks=20),
            online_adapter=_SlowOnline(),  # type: ignore[arg-type]
        )
        res_srch, err_srch = srch_exec.call(
            "search_music",
            {"query": "Cancel", "allow_network": True, "task_id": "srch-mid"},
            request_id=604,
            stop_token=tok_srch,
        )
        assert err_srch is True and res_srch["error"]["code"] == "PLAYBACK_ABORTED"
        assert online_calls == 1
        assert srch_exec.tasks.get("srch-mid").status == "cancelled"  # type: ignore[union-attr]

        # C. Cancel right BEFORE DB commit (post-artifact write rollback!) in arrange_song
        tok_pre_db = StopToken()
        from lyraforge.library import store as store_mod

        orig_arr_to_midi = store_mod.arrangement_to_midi_bytes

        def _abort_just_before_commit(arr_obj: Any) -> bytes:
            tok_pre_db.request_stop("cancel right before DB commit")
            return orig_arr_to_midi(arr_obj)

        monkeypatch.setattr(store_mod, "arrangement_to_midi_bytes", _abort_just_before_commit)
        perf_files_before = sorted((tmp_path / "mcp_cancel_lib").rglob("*.json"))
        res_pre_db, err_pre_db = executor.call(
            "arrange",
            {"song_id": imp.song.id, "style": "melody", "task_id": "arr-pre-db"},
            request_id=605,
            stop_token=tok_pre_db,
        )
        monkeypatch.undo()
        assert err_pre_db is True and res_pre_db["error"]["code"] == "PLAYBACK_ABORTED"
        assert len(store.get_song(imp.song.id).arrangements) == 1
        assert sorted((tmp_path / "mcp_cancel_lib").rglob("*.json")) == perf_files_before

        # D. Late cancel AFTER save / DB commit completes -> must stay completed & persisted!
        # D1: export_score after atomic_write_bytes
        from lyraforge.mcp import tools as tools_mod

        orig_atomic_mcp = tools_mod.atomic_write_bytes
        late_exp_tok = StopToken()

        def _cancel_after_export_write(dest: Path, data: bytes) -> Path:
            res = orig_atomic_mcp(dest, data)
            late_exp_tok.request_stop("late cancel after file write")
            return res

        exp_dest = tmp_path / "late_exported.mid"
        monkeypatch.setattr(tools_mod, "atomic_write_bytes", _cancel_after_export_write)
        res_late_exp, err_late_exp = executor.call(
            "export_score",
            {
                "arrangement_id": arr.id,
                "format": "midi",
                "output_path": str(exp_dest),
                "task_id": "exp-late",
            },
            request_id=606,
            stop_token=late_exp_tok,
        )
        monkeypatch.undo()
        assert err_late_exp is False and res_late_exp["ok"] is True
        assert exp_dest.is_file() and exp_dest.stat().st_size > 0
        assert registry.get("exp-late").status == "completed"  # type: ignore[union-attr]
        # Post-completion cancel attempt via notifications/cancelled also does not revert status
        srv = LyraMCPServer(executor)
        srv.handle_message(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 606},
            })
        )
        assert registry.get("exp-late").status == "completed"  # type: ignore[union-attr]

        # D2: save_to_library after atomic DB commit
        orig_save = store.save_library_updates
        late_save_tok = StopToken()

        def _cancel_after_db_commit(**kw: Any) -> dict[str, Any]:
            out = orig_save(**kw)
            late_save_tok.request_stop("late cancel after DB commit")
            return out

        monkeypatch.setattr(store, "save_library_updates", _cancel_after_db_commit)
        res_late_save, err_late_save = executor.call(
            "save_to_library",
            {
                "song_id": imp.song.id,
                "title": "Committed Before Late Cancel",
                "arrangement_id": arr.id,
                "is_favorite": True,
                "task_id": "save-late",
            },
            request_id=607,
            stop_token=late_save_tok,
        )
        monkeypatch.undo()
        assert err_late_save is False and res_late_save["ok"] is True
        assert store.get_song(imp.song.id).song.title == "Committed Before Late Cancel"
        assert store.get_arrangement(arr.id).is_favorite is True
        assert registry.get("save-late").status == "completed"  # type: ignore[union-attr]

        # Also avoid URLError unused import lint
        assert urllib.error.URLError is not None


# ---------------------------------------------------------------------------
# 4. P2: Subprocess & derived process-tree lifecycle hardening
# ---------------------------------------------------------------------------


def test_subprocess_derived_process_tree_timeout_cancel_orphan_pipes_and_stress(
    tmp_path: Path,
) -> None:
    def _drain_threads() -> list[str]:
        return [th.name for th in threading.enumerate() if "-drain" in th.name and th.is_alive()]

    # A. Child spawns sleeping grandchild, timeout kills BOTH parent and grandchild cleanly
    gpid_timeout = tmp_path / "gpid_timeout.txt"
    timeout_script = (
        "import pathlib, subprocess, sys, time\n"
        f"p = pathlib.Path({str(gpid_timeout)!r})\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "p.write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    work_a = tmp_path / "work_a"
    with pytest.raises(LyraError) as exc_t:
        run_bounded_subprocess(
            [sys.executable, "-c", timeout_script],
            work_dir=work_a,
            prefix="tree-to",
            timeout_s=0.35,
            stop_token=None,
            cancel_message="cancelled",
            timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
            timeout_message="tree timed out",
        )
    assert exc_t.value.code == ErrorCode.MEDIA_DECODE_FAILED
    assert gpid_timeout.is_file()
    dead_to_pid = int(gpid_timeout.read_text(encoding="utf-8"))
    assert _wait_pid_dead(dead_to_pid, timeout_s=5.0)
    assert list(work_a.glob("*")) == []
    assert not _drain_threads()

    # B. Active StopToken cancellation kills both parent AND grandchild
    gpid_cancel = tmp_path / "gpid_cancel.txt"
    cancel_script = (
        "import pathlib, subprocess, sys, time\n"
        f"p = pathlib.Path({str(gpid_cancel)!r})\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "p.write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    work_b = tmp_path / "work_b"
    tok = StopToken()

    def _cancel_once_spawned() -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not gpid_cancel.is_file():
            time.sleep(0.02)
        tok.request_stop("user cancelled process tree")

    t_trig = threading.Thread(target=_cancel_once_spawned, daemon=True)
    t_trig.start()
    with pytest.raises(LyraError) as exc_c:
        run_bounded_subprocess(
            [sys.executable, "-c", cancel_script],
            work_dir=work_b,
            prefix="tree-cancel",
            timeout_s=15.0,
            stop_token=tok,
            cancel_message="cancelled tree",
            timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
            timeout_message="timed out",
        )
    t_trig.join(timeout=2.0)
    assert exc_c.value.code == ErrorCode.PLAYBACK_ABORTED
    dead_c_pid = int(gpid_cancel.read_text(encoding="utf-8"))
    assert _wait_pid_dead(dead_c_pid, timeout_s=5.0)
    assert list(work_b.glob("*")) == []
    assert not _drain_threads()

    # C. Parent exits 0 cleanly WHILE grandchild keeps holding inherited stdout/stderr pipes open
    #    Use base interpreter directly so Windows venv trampolines do not mask ParentProcessId link.
    raw_base_py = getattr(sys, "_base_executable", sys.executable)
    direct_py = raw_base_py if raw_base_py and Path(raw_base_py).is_file() else sys.executable
    gpid_orphan = tmp_path / "gpid_orphan.txt"
    orphan_pipe_script = (
        "import pathlib, subprocess, sys\n"
        f"p = pathlib.Path({str(gpid_orphan)!r})\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "p.write_text(str(child.pid), encoding='utf-8')\n"
        "sys.stdout.buffer.write(b'PARENT_EXITED_OK\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "sys.exit(0)\n"
    )
    work_c = tmp_path / "work_c"
    t0 = time.monotonic()
    res_orphan = run_bounded_subprocess(
        [direct_py, "-c", orphan_pipe_script],
        work_dir=work_c,
        prefix="orphan-pipe",
        timeout_s=15.0,
        stop_token=None,
        cancel_message="cancelled",
        timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
        timeout_message="timeout",
        drain_grace_s=0.25,
    )
    elapsed_orphan = time.monotonic() - t0
    assert elapsed_orphan < 10.0  # Did NOT block 30s waiting on grandchild pipe!
    assert res_orphan.returncode == 0
    assert b"PARENT_EXITED_OK" in res_orphan.stdout_tail
    dead_o_pid = int(gpid_orphan.read_text(encoding="utf-8"))
    assert _wait_pid_dead(dead_o_pid, timeout_s=5.0)
    assert list(work_c.glob("*")) == []
    assert not _drain_threads()

    # D. Rapid start/stop stress loop across multiple tasks with concurrent stdout/stderr flood
    work_d = tmp_path / "work_d"

    def _run_one(idx: int) -> None:
        script = (
            "import sys; "
            f"sys.stdout.buffer.write(b'S-{idx}-' * 400); "
            f"sys.stderr.buffer.write(b'E-{idx}-' * 400); "
            "sys.stdout.buffer.flush(); sys.stderr.buffer.flush()"
        )
        res = run_bounded_subprocess(
            [sys.executable, "-c", script],
            work_dir=work_d,
            prefix=f"stress-{idx}",
            timeout_s=10.0,
            stop_token=None,
            cancel_message="cancelled",
            timeout_code=ErrorCode.MEDIA_DECODE_FAILED,
            timeout_message="timeout",
            max_log_bytes=4096,
            tail_bytes=512,
        )
        assert res.returncode == 0
        assert res.peak_disk_bytes <= 4096

    with ThreadPoolExecutor(max_workers=4) as pool:
        for fut in [pool.submit(_run_one, i) for i in range(10)]:
            fut.result(timeout=15.0)
    assert list(work_d.glob("*")) == []
    assert not _drain_threads()
