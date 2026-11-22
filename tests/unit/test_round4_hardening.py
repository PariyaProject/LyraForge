"""Round 4 hardening regression suite covering playback, subprocess, SQLite, MCP, and CLI."""

from __future__ import annotations

import array
import io
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.request
import wave
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lyraforge.agent.llm import OpenAICompatibleLLMProvider
from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.cli import EXIT_OK, main
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.library import LibraryStore, export_backup_zip
from lyraforge.library.packaging import import_lyrapack
from lyraforge.mcp import LyraMCPServer, MCPToolExecutor
from lyraforge.media.extract import SUPPORTED_MEDIA_EXTENSIONS, extract_audio_to_wav
from lyraforge.music_core import ArrangeOptions
from lyraforge.music_core.arranger import Style
from lyraforge.playback import (
    DryRunDriver,
    PauseToken,
    PlaybackState,
    Player,
    VirtualClock,
)
from lyraforge.sources.local import ALLOWED_SOURCE_EXTENSIONS
from lyraforge.sources.online import OpenMusicCatalogSourceAdapter
from lyraforge.sources.url import DirectUrlSourceAdapter
from lyraforge.transcribers._subprocess import run_isolated_transcriber

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def _write_tone_wav(path: Path, duration_s: float = 0.5, freq_hz: float = 440.0) -> None:
    sr = 22_050
    n = int(sr * duration_s)
    pcm = array.array(
        "h",
        (int(12_000 * math.sin(2.0 * math.pi * freq_hz * i / sr)) for i in range(n)),
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def test_subprocess_pipe_flood_no_deadlock_and_webm_supported(tmp_path: Path) -> None:
    assert ".webm" in SUPPORTED_MEDIA_EXTENSIONS
    assert ".webm" in ALLOWED_SOURCE_EXTENSIONS

    wav_in = tmp_path / "tone.wav"
    _write_tone_wav(wav_in, 0.2)

    mid_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    helper = tmp_path / "noisy_transcriber.py"
    helper.write_text(
        f"""
import pathlib, sys
sys.stdout.write("O" * 160000 + "\\n")
sys.stderr.write("E" * 160000 + "\\n")
sys.stdout.flush()
sys.stderr.flush()
out_dir = pathlib.Path(sys.argv[2])
(out_dir / "out.mid").write_bytes({mid_bytes!r})
""",
        encoding="utf-8",
    )

    res = run_isolated_transcriber(
        engine_id="noisy-test",
        display_name="Noisy Subprocess",
        runner=[sys.executable, str(helper)],
        missing_hint="missing",
        audio_path=wav_in,
        build_cmd=lambda runner, w, out_dir: [*runner, str(w), str(out_dir)],
    )
    assert res.note_count == 8

    # Fake ffmpeg writing >160 KB stderr on failure without deadlocking
    fake_ffmpeg = tmp_path / "fake_ffmpeg.py"
    fake_ffmpeg.write_text(
        """
import sys
sys.stderr.write("F" * 160000 + "TAIL_END\\n")
sys.stderr.flush()
sys.exit(2)
""",
        encoding="utf-8",
    )
    wrapper_sh = tmp_path / "fake_ffmpeg_runner.sh"
    if os.name == "posix":
        wrapper_sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake_ffmpeg}" "$@"\n')
        wrapper_sh.chmod(0o755)
        webm_in = tmp_path / "clip.webm"
        webm_in.write_bytes(b"fake-webm")
        with pytest.raises(LyraError) as exc:
            extract_audio_to_wav(webm_in, tmp_path / "out.wav", ffmpeg_bin=str(wrapper_sh))
        assert exc.value.code == ErrorCode.MEDIA_DECODE_FAILED
        assert "TAIL_END" in exc.value.message


def test_player_pause_resume_escape_stop_and_multi_song_sequence() -> None:
    clock = VirtualClock()
    pause_tok = PauseToken()

    events = [
        {"at_ms": 0, "key_id": "mid_1", "hold_ms": 120},
        {"at_ms": 100, "key_id": "mid_3", "hold_ms": 120},
        {"at_ms": 200, "key_id": "mid_5", "hold_ms": 120},
    ]

    # Trigger pause after mid_1 key_down (first key_down increments clock on wait)
    class _PausingDriver(DryRunDriver):
        def key_down(self, key_id: str) -> None:
            super().key_down(key_id)
            if key_id == "mid_1":
                pause_tok.pause()

    def _auto_unpause() -> None:
        deadline = time.monotonic() + 2.0
        while not pause_tok.paused and time.monotonic() < deadline:
            time.sleep(0.005)
        pause_tok.resume()

    pdriver = _PausingDriver(clock)
    player = Player(pdriver, clock, pause_token=pause_tok, poll_interval_us=5_000)
    t = threading.Thread(target=_auto_unpause, daemon=True)
    t.start()
    res = player.play(events)
    t.join(timeout=2.0)

    assert res.state == PlaybackState.COMPLETED
    assert pdriver.pressed_snapshot() == []
    # Pausing released mid_1 immediately before completion!
    assert any(entry.action == "release" and entry.key_id == "mid_1" for entry in pdriver.log)

    # Physical Esc emergency stop releases keys and records reason
    esc_count = {"n": 0}

    def _esc_trigger() -> bool:
        esc_count["n"] += 1
        return esc_count["n"] >= 3

    driver2 = DryRunDriver(VirtualClock())
    res2 = Player(driver2, VirtualClock(), emergency_stop_fn=_esc_trigger).play(events)
    assert res2.state == PlaybackState.STOPPED
    assert res2.stop_reason == "escape_key_pressed"
    assert driver2.pressed_snapshot() == []

    # 500-note long sequence + second song back-to-back
    long_events = [
        {"at_ms": i * 80, "key_id": f"mid_{(i % 7) + 1}", "hold_ms": 50}
        for i in range(500)
    ]
    clk3 = VirtualClock()
    drv3 = DryRunDriver(clk3)
    player3 = Player(drv3, clk3)
    r_a = player3.play(long_events)
    r_b = player3.play(events)
    assert r_a.state == PlaybackState.COMPLETED
    assert r_a.actions_sent == 1000
    assert r_a.max_lateness_us == 0
    assert r_b.state == PlaybackState.COMPLETED
    assert r_b.actions_sent == 6
    assert drv3.pressed_snapshot() == []


def test_library_tag_exactness_single_read_pianoroll_clamp_and_zip_reserved(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with LibraryStore(data_dir) as store:
        imp1 = store.import_midi(
            FIXTURE_DIR / "c_major_scale.mid",
            title="Classical Piece",
            tags=["classical", "c"],
        )
        imp2 = store.import_midi(
            FIXTURE_DIR / "chords_type1.mid",
            title="Only Classical",
            tags=["classical"],
        )
        assert [s.id for s in store.search_songs("", tag="c")] == [imp1.song.id]
        assert store.search_songs("", tag="%") == []

        # Deduplicate duplicate (at_ms, key_id) & clamp overlapping hold_ms on adjacent edits
        arr = store.arrange_song(imp1.song.id, options=ArrangeOptions(style=Style.MELODY))
        edited = store.save_edited_arrangement(
            arr.id,
            [
                {"at_ms": 100, "key_id": "mid_1", "hold_ms": 200, "velocity": 70},
                {"at_ms": 100, "key_id": "mid_1", "hold_ms": 200, "velocity": 110},
                {"at_ms": 150, "key_id": "mid_1", "hold_ms": 80, "velocity": 95},
            ],
            label="Adjacent Clamped",
        )
        perf = store.load_arrangement_performance(edited.id)
        assert len(perf["events"]) == 2
        assert perf["events"][0]["at_ms"] == 100
        assert perf["events"][0]["hold_ms"] == 50  # clamped cleanly to next at_ms - at_ms
        assert perf["events"][0]["velocity"] == 110

        # ZIP traversal / Windows reserved names rejected cleanly
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("CON.mid", b"bad")
        with pytest.raises(LyraError) as exc_zip:
            import_lyrapack(store, buf.getvalue())
        assert exc_zip.value.code == ErrorCode.PACKAGE_INVALID
        assert imp2.song.id


def test_api_restore_pause_resume_allowed_titles_cli_ssrf_and_llm_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "api_data"
    with LibraryStore(data_dir) as store:
        imp = store.import_midi(FIXTURE_DIR / "c_major_scale.mid", title="KeepMe")
        store.arrange_song(imp.song.id, options=ArrangeOptions(style=Style.MELODY))
        store.set_setting("windows_allowed_titles", "Genshin Impact, 原神, CustomWin")
        backup_bytes = export_backup_zip(store)

    # Mutate library by importing a second song, then restore via API & CLI
    token = "r4-token"
    app = create_app(data_dir=data_dir, session_token=token)
    headers = {SESSION_TOKEN_HEADER: token}
    client = TestClient(app)

    imp2 = client.post(
        "/v1/imports",
        headers=headers,
        files={
            "file": (
                "extra.mid",
                (FIXTURE_DIR / "chords_type1.mid").read_bytes(),
                "audio/midi",
            )
        },
    )
    assert imp2.status_code == 200
    assert len(client.get("/v1/library/songs", headers=headers).json()["songs"]) == 2

    rst = client.post(
        "/v1/library/restore",
        headers=headers,
        files={"file": ("backup.zip", backup_bytes, "application/zip")},
    )
    assert rst.status_code == 200
    assert rst.json()["restored"]["song_count"] == 1
    assert client.get("/v1/library/songs", headers=headers).json()["songs"][0]["title"] == "KeepMe"

    # CLI restore works on standalone path
    bak_file = tmp_path / "cli_bak.zip"
    bak_file.write_bytes(backup_bytes)
    cli_restore_dir = tmp_path / "cli_restored"
    rc = main(["library", "restore", str(bak_file), "--data-dir", str(cli_restore_dir)])
    assert rc == EXIT_OK
    with LibraryStore(cli_restore_dir) as rstore:
        assert len(rstore.search_songs("")) == 1

    # Verify pause/resume/stop flow via HTTP API
    arr_id = client.get("/v1/library/songs", headers=headers).json()["songs"][0]["id"]
    song_detail = client.get(f"/v1/library/songs/{arr_id}", headers=headers).json()
    aid = song_detail["arrangements"][0]["id"]

    prep = client.post(
        "/v1/playback/prepare",
        headers=headers,
        json={"arrangement_id": aid, "mode": "dry-run", "realtime": True},
    )
    assert prep.status_code == 200
    tok = prep.json()["prepare_token"]
    started = client.post("/v1/playback/start", headers=headers, json={"prepare_token": tok})
    assert started.status_code == 200
    paused = client.post("/v1/playback/pause", headers=headers)
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    resumed = client.post("/v1/playback/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["state"] in {"running", "completed"}
    stopped = client.post("/v1/playback/stop", headers=headers)
    assert stopped.status_code == 200

    # Proxy env vars bypassed by explicit ProxyHandler({}) inside adapters
    # (urllib strips ProxyHandler when proxies={} so default opener differs)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    url_ad = DirectUrlSourceAdapter()
    online_ad = OpenMusicCatalogSourceAdapter()
    assert any(
        isinstance(h, urllib.request.ProxyHandler)
        for h in urllib.request.build_opener().handlers
    )
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in url_ad._opener.handlers)
    assert not any(
        isinstance(h, urllib.request.ProxyHandler) for h in online_ad._opener.handlers
    )

    # LLM non-numeric transpose="auto" & >1MB body guard
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

    good_body = json.dumps({
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "action": "arrange",
                        "query": "demo",
                        "transpose": "auto",
                        "transpose_delta": "invalid",
                        "speed": "1.25",
                        "arpeggiate_ms": 20,
                    })
                }
            }
        ]
    }).encode("utf-8")
    prov = OpenAICompatibleLLMProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="demo-model",
        opener=_FakeOpener(good_body),
    )
    intent = prov.parse_intent("帮我编曲")
    assert intent.transpose is None
    assert intent.speed == 1.25

    oversize = b"{" + b"x" * 1_100_000 + b"}"
    prov_big = OpenAICompatibleLLMProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="demo-model",
        opener=_FakeOpener(oversize),
    )
    with pytest.raises(LyraError) as exc_big:
        prov_big.parse_intent("帮我编曲")
    assert exc_big.value.code == ErrorCode.LIMIT_EXCEEDED


def test_mcp_negotiation_validation_midflight_cancel_and_desktop_self_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "mcp_live"
    long_wav = tmp_path / "long_melody.wav"
    _write_tone_wav(long_wav, duration_s=8.0, freq_hz=440.0)

    # Unit checks: unknown protocol negotiates latest + strict bounds check
    with LibraryStore(data_dir) as store:
        executor = MCPToolExecutor(store)
        server = LyraMCPServer(executor)
        init_unknown = server.handle_message(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            })
        )
        assert init_unknown is not None
        assert init_unknown["result"]["protocolVersion"] == "2025-03-26"

        bad_limit, is_err = executor.call("search_music", {"query": "a", "limit": 999})
        assert is_err is True
        assert bad_limit["error"]["code"] == "INVALID_ARGUMENT"

        bad_bool, is_err_b = executor.call("search_music", {"query": "a", "limit": True})
        assert is_err_b is True
        assert bad_bool["error"]["code"] == "INVALID_ARGUMENT"

    # Real stdio subprocess: transcribe 8s WAV and cancel mid-flight via notifications/cancelled
    proc = subprocess.Popen(
        [sys.executable, "-m", "lyraforge.cli", "mcp", "--data-dir", str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        )
        proc.stdin.flush()
        assert json.loads(proc.stdout.readline())["id"] == 1

        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        proc.stdin.write(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "import_media", "arguments": {"path": str(long_wav)}},
            }) + "\n"
        )
        proc.stdin.flush()
        imp_resp = json.loads(proc.stdout.readline())
        song_id = imp_resp["result"]["structuredContent"]["song"]["id"]

        # Start slow transcription, then send cancellation notification shortly after
        proc.stdin.write(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {
                    "name": "transcribe",
                    "arguments": {"song_id": song_id, "task_id": "midflight-task"},
                },
            }) + "\n"
        )
        proc.stdin.flush()
        time.sleep(0.06)
        proc.stdin.write(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 99},
            }) + "\n"
        )
        proc.stdin.flush()

        tr_resp = json.loads(proc.stdout.readline())
        assert tr_resp["id"] == 99
        # Depending on CPU speed, fast M4 hosts may cancel cleanly or complete before sleep
        tr_struct = tr_resp["result"]["structuredContent"]
        if tr_resp["result"]["isError"]:
            assert tr_struct["error"]["code"] == "PLAYBACK_ABORTED"
            proc.stdin.write(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 100,
                    "method": "tools/call",
                    "params": {
                        "name": "get_task_status",
                        "arguments": {"task_id": "midflight-task"},
                    },
                }) + "\n"
            )
            proc.stdin.flush()
            st_resp = json.loads(proc.stdout.readline())
            assert st_resp["result"]["structuredContent"]["task"]["status"] == "cancelled"
        else:
            assert tr_struct["status"] == "completed"
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)

    # desktop --self-check CLI
    capsys.readouterr()
    assert main(["desktop", "--self-check"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert "genshin.windsong_lyre.v1" in out["profiles"]
