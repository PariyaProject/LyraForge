"""Integration tests for the local FastAPI service (lyraforge.api)."""

from __future__ import annotations

import io
import sqlite3
import sys
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.cli import EXIT_ERROR, main

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_api_auth_library_preview_and_playback_lifecycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "api_data"
    token = "test-session-token-123"
    app = create_app(
        data_dir=data_dir,
        session_token=token,
        cors_origins=["http://127.0.0.1:5173"],
    )
    headers = {SESSION_TOKEN_HEADER: token}
    client = TestClient(app)

    # /health is unauthenticated and reports platform capabilities
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert h.json()["windows_playback_available"] is (sys.platform == "win32")

    # Protected endpoints reject missing or wrong token
    assert client.get("/v1/profiles").status_code == 401
    assert client.get("/v1/profiles", headers={SESSION_TOKEN_HEADER: "wrong"}).status_code == 401

    # Profiles
    profs = client.get("/v1/profiles", headers=headers)
    assert profs.status_code == 200
    assert profs.json()["profiles"][0]["id"] == "genshin.harmonic_keys.v1"

    prof_detail = client.get("/v1/profiles/genshin.harmonic_keys.v1", headers=headers)
    assert prof_detail.status_code == 200
    assert prof_detail.json()["key_count"] == 21

    # Import invalid MIDI fails cleanly with 400
    bad_imp = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("broken.mid", (FIXTURE_DIR / "broken" / "not_midi.mid").read_bytes())},
    )
    assert bad_imp.status_code == 400
    assert bad_imp.json()["error"]["code"] == "MEDIA_DECODE_FAILED"

    # Import valid MIDI
    midi_bytes = (FIXTURE_DIR / "chords_type1.mid").read_bytes()
    imp = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("chords_type1.mid", midi_bytes, "audio/midi")},
        data={"title": "API Chords", "artist": "Unit", "tags": "api,lyre"},
    )
    assert imp.status_code == 200
    imp_json = imp.json()
    assert imp_json["deduplicated"] is False
    song_id = imp_json["song"]["id"]

    # Search and inspect song
    songs = client.get("/v1/library/songs", params={"q": "API"}, headers=headers)
    assert songs.status_code == 200
    assert len(songs.json()["songs"]) == 1

    song_detail = client.get(f"/v1/library/songs/{song_id}", headers=headers)
    assert song_detail.status_code == 200
    assert song_detail.json()["song"]["title"] == "API Chords"

    # Arrange
    arr_resp = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced"},
    )
    assert arr_resp.status_code == 200
    arr_id = arr_resp.json()["arrangement"]["id"]

    arr_detail = client.get(f"/v1/arrangements/{arr_id}", headers=headers)
    assert arr_detail.status_code == 200
    assert arr_detail.json()["performance"]["arrangement_id"] == arr_id
    assert arr_detail.json()["report"]["stats"]["emitted_events"] > 0

    # Preview render & WAV streaming
    pv = client.post("/v1/preview", headers=headers, json={"arrangement_id": arr_id})
    assert pv.status_code == 200
    wav_resp = client.get(pv.json()["preview_url"], headers=headers)
    assert wav_resp.status_code == 200
    assert wav_resp.headers["content-type"].startswith("audio/wav")
    with wave.open(io.BytesIO(wav_resp.content), "rb") as wf:
        assert wf.getnframes() > 0

    # Unauthorized playback/start rejected without prepare_token
    bad_start = client.post(
        "/v1/playback/start",
        headers=headers,
        json={"prepare_token": "forged-token"},
    )
    assert bad_start.status_code == 403
    assert bad_start.json()["error"]["code"] == "PERMISSION_REQUIRED"

    # Non-Windows rejects mode="windows" at prepare time
    if sys.platform != "win32":
        win_prep = client.post(
            "/v1/playback/prepare",
            headers=headers,
            json={"arrangement_id": arr_id, "mode": "windows"},
        )
        assert win_prep.status_code == 400
        assert win_prep.json()["error"]["code"] == "INVALID_ARGUMENT"

    # Prepare -> Start (DryRun) -> wait for completion -> Stop -> reuse token fails
    prep = client.post(
        "/v1/playback/prepare",
        headers=headers,
        json={"arrangement_id": arr_id, "mode": "dry-run", "realtime": False},
    )
    assert prep.status_code == 200
    prep_token = prep.json()["prepare_token"]
    assert prep.json()["sends_os_input"] is False

    started = client.post(
        "/v1/playback/start",
        headers=headers,
        json={"prepare_token": prep_token},
    )
    assert started.status_code == 200
    assert started.json()["sends_os_input"] is False

    # Wait briefly for virtual-clock background DryRun to finish
    for _ in range(50):
        st = client.get("/v1/playback/status", headers=headers).json()
        if st["state"] != "running":
            break
        time.sleep(0.02)
    assert st["state"] == "completed"
    assert st["keys_still_pressed"] == []
    assert st["last_result"]["actions_sent"] == st["last_result"]["actions_total"] > 0

    # Token is single-use (cannot be replayed after completion)
    reuse = client.post(
        "/v1/playback/start",
        headers=headers,
        json={"prepare_token": prep_token},
    )
    assert reuse.status_code == 403

    stopped = client.post("/v1/playback/stop", headers=headers)
    assert stopped.status_code == 200

    # Verify session persisted in SQLite
    conn = sqlite3.connect(data_dir / "library.db")
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM playback_sessions").fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()


def test_api_realtime_stop_and_serve_loopback_guard(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "rt_data"
    token = "rt-token"
    app = create_app(data_dir=data_dir, session_token=token)
    headers = {SESSION_TOKEN_HEADER: token}
    client = TestClient(app)

    imp = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("chords.mid", (FIXTURE_DIR / "chords_type1.mid").read_bytes())},
    )
    song_id = imp.json()["song"]["id"]
    arr_id = client.post(
        "/v1/jobs/arrange", headers=headers, json={"song_id": song_id}
    ).json()["arrangement"]["id"]

    prep = client.post(
        "/v1/playback/prepare",
        headers=headers,
        json={"arrangement_id": arr_id, "mode": "dry-run", "realtime": True},
    ).json()
    client.post(
        "/v1/playback/start",
        headers=headers,
        json={"prepare_token": prep["prepare_token"]},
    )
    time.sleep(0.05)
    stopped = client.post("/v1/playback/stop", headers=headers).json()
    assert stopped["state"] in {"stopped", "completed"}
    assert stopped["keys_still_pressed"] == []

    # Serve refuses non-loopback host
    assert main(["serve", "--host", "0.0.0.0"]) == EXIT_ERROR
    assert "INVALID_ARGUMENT" in capsys.readouterr().err


def test_api_static_dir_serves_bootstrap_html_and_assets(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>App</title></head>"
        "<body><div id='app'></div></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('lyraforge');", encoding="utf-8")

    app = create_app(data_dir=tmp_path / "data", session_token="boot-tok-999", static_dir=dist)
    client = TestClient(app)

    idx = client.get("/")
    assert idx.status_code == 200
    assert "window.__LYRAFORGE_CONFIG__" in idx.text
    assert "boot-tok-999" in idx.text

    js = client.get("/assets/app.js")
    assert js.status_code == 200
    assert "lyraforge" in js.text


def test_api_transcribers_and_transcribe_job_flow(tmp_path: Path) -> None:
    from lyraforge.instruments import load_builtin_profile
    from lyraforge.library import LibraryStore
    from lyraforge.music_core import arrange, build_performance, load_midi_file
    from lyraforge.preview import synthesize_performance_to_wav

    data_dir = tmp_path / "tr_api_data"
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    perf = build_performance(score, prof, arrange(score, prof))
    wav_file = tmp_path / "scale.wav"
    synthesize_performance_to_wav(perf, wav_file)

    with LibraryStore(data_dir) as store:
        imp = store.import_audio(wav_file, title="API Audio Scale")

    token = "tr-tok"
    client = TestClient(create_app(data_dir=data_dir, session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    engines = client.get("/v1/transcribers", headers=headers)
    assert engines.status_code == 200
    assert any(e["id"] == "builtin-mono" for e in engines.json()["transcribers"])

    tr_resp = client.post(
        "/v1/jobs/transcribe",
        headers=headers,
        json={"song_id": imp.song.id, "engine_id": "builtin-mono"},
    )
    assert tr_resp.status_code == 200
    assert tr_resp.json()["transcription"]["note_count"] >= 6

    arr_resp = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": imp.song.id, "style": "melody"},
    )
    assert arr_resp.status_code == 200
    assert arr_resp.json()["arrangement"]["event_count"] >= 6


def test_api_audio_upload_async_transcribe_cancel_exports_and_settings(tmp_path: Path) -> None:
    from lyraforge.instruments import load_builtin_profile
    from lyraforge.music_core import arrange, build_performance, load_midi_file
    from lyraforge.preview import synthesize_performance_to_wav

    data_dir = tmp_path / "async_api_data"
    prof = load_builtin_profile()
    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    perf = build_performance(score, prof, arrange(score, prof))
    wav_file = tmp_path / "upload_scale.wav"
    synthesize_performance_to_wav(perf, wav_file)

    token = "async-tok"
    client = TestClient(create_app(data_dir=data_dir, session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    # Upload WAV directly through /v1/imports
    up = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("upload_scale.wav", wav_file.read_bytes(), "audio/wav")},
        data={"title": "Uploaded Audio", "tags": "wav,m2"},
    )
    assert up.status_code == 200
    assert up.json()["source"]["kind"] == "audio"
    song_id = up.json()["song"]["id"]

    # Async transcription job -> poll to completed
    sub = client.post(
        "/v1/jobs/transcribe",
        headers=headers,
        json={"song_id": song_id, "engine_id": "builtin-mono", "async_mode": True},
    )
    assert sub.status_code == 200
    job_id = sub.json()["job"]["id"]

    job_state = sub.json()["job"]
    for _ in range(100):
        job_state = client.get(f"/v1/jobs/{job_id}", headers=headers).json()["job"]
        if job_state["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    assert job_state["status"] == "completed"
    assert job_state["transcription"]["note_count"] >= 6

    jobs_list = client.get("/v1/jobs", headers=headers)
    assert jobs_list.status_code == 200
    assert len(jobs_list.json()["jobs"]) == 1

    # Cancel endpoint works cleanly (even after completion / mid-flight)
    cancelled = client.post(f"/v1/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200

    # Arrange and export MIDI + JSON
    arr_id = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced"},
    ).json()["arrangement"]["id"]

    exp_mid = client.get(f"/v1/arrangements/{arr_id}/export.mid", headers=headers)
    assert exp_mid.status_code == 200
    assert exp_mid.content.startswith(b"MThd")

    exp_json = client.get(f"/v1/arrangements/{arr_id}/export.json", headers=headers)
    assert exp_json.status_code == 200
    assert exp_json.json()["arrangement_id"] == arr_id

    # Settings round-trip
    upd = client.post(
        "/v1/settings",
        headers=headers,
        json={"key": "default_style", "value": "rich"},
    )
    assert upd.status_code == 200
    assert upd.json()["settings"]["default_style"] == "rich"
    got = client.get("/v1/settings", headers=headers)
    assert got.json()["settings"]["default_style"] == "rich"


def test_api_m3_profiles_ab_edit_favorite_vote_and_compare(tmp_path: Path) -> None:
    data_dir = tmp_path / "m3_api_data"
    token = "m3-tok"
    client = TestClient(create_app(data_dir=data_dir, session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    profs = client.get("/v1/profiles", headers=headers)
    assert profs.status_code == 200
    profile_ids = [p["id"] for p in profs.json()["profiles"]]
    assert profile_ids[0] == "genshin.harmonic_keys.v1"
    assert "genshin.windsong_lyre.v1" in profile_ids
    assert "genshin.floral_zither.v1" in profile_ids

    mid_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    up = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("c_major_scale.mid", mid_bytes, "audio/midi")},
        data={"title": "C Scale M3"},
    )
    assert up.status_code == 200
    song_id = up.json()["song"]["id"]

    ab = client.post(
        "/v1/jobs/arrange-ab",
        headers=headers,
        json={
            "song_id": song_id,
            "instrument_profile_id": "genshin.floral_zither.v1",
            "variant_a": {"style": "melody", "arpeggiate_ms": 0, "label": "主旋律A"},
            "variant_b": {"style": "balanced", "arpeggiate_ms": 15, "label": "均衡B"},
        },
    )
    assert ab.status_code == 200
    ab_json = ab.json()
    id_a = ab_json["arrangement_a"]["id"]
    id_b = ab_json["arrangement_b"]["id"]
    assert ab_json["comparison"]["winner"] in {id_a, id_b, "tie"}

    detail = client.get(f"/v1/arrangements/{id_a}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["report"]["quality"]["overall_score"] >= 80.0
    events = detail.json()["performance"]["events"]

    edited = client.post(
        f"/v1/arrangements/{id_a}/edit",
        headers=headers,
        json={
            "events": [*events, {"at_ms": events[-1]["at_ms"] + 300, "key_id": "high_1"}],
            "label": "编辑子节点",
        },
    )
    assert edited.status_code == 200
    child_id = edited.json()["arrangement"]["id"]
    assert edited.json()["arrangement"]["parent_id"] == id_a

    fav = client.post(
        f"/v1/arrangements/{child_id}/favorite",
        headers=headers,
        json={"is_favorite": True},
    )
    assert fav.status_code == 200
    assert fav.json()["arrangement"]["is_favorite"] is True

    vote = client.post(
        f"/v1/arrangements/{child_id}/vote",
        headers=headers,
        json={"vote": 1},
    )
    assert vote.status_code == 200
    assert vote.json()["arrangement"]["user_vote"] == 1

    cmp = client.post(
        "/v1/arrangements/compare",
        headers=headers,
        json={"arrangement_a_id": id_a, "arrangement_b_id": child_id},
    )
    assert cmp.status_code == 200
    assert "overall_score" in cmp.json()["metrics"]

    # M4 Agent tools & natural-language orchestration
    tools = client.get("/v1/agent/tools", headers=headers)
    assert tools.status_code == 200
    assert "playback.start" in tools.json()["forbidden_tools"]

    agent_ok = client.post(
        "/v1/agent/run",
        headers=headers,
        json={"prompt": "找《C Scale M3》转成镜花之琴主旋律并优化"},
    )
    assert agent_ok.status_code == 200
    assert agent_ok.json()["status"] == "completed"
    assert agent_ok.json()["selected_arrangement"]["profile_id"] == "genshin.floral_zither.v1"

    agent_gate = client.post(
        "/v1/agent/run",
        headers=headers,
        json={"prompt": "导入 https://93.184.216.34/demo.mid 编曲", "allow_network": False},
    )
    assert agent_gate.status_code == 200
    assert agent_gate.json()["status"] == "needs_confirmation"
    assert agent_gate.json()["requires_confirmation"] is True

    agent_ssrf = client.post(
        "/v1/agent/run",
        headers=headers,
        json={"prompt": "导入 http://127.0.0.1/secret.mid", "allow_network": True},
    )
    assert agent_ssrf.status_code == 400

    # M5 filters, .lyrapack export/import, and library backup
    fav_songs = client.get("/v1/library/songs?favorites_only=true", headers=headers)
    assert fav_songs.status_code == 200
    assert any(s["id"] == song_id for s in fav_songs.json()["songs"])

    pack_denied = client.post(
        f"/v1/arrangements/{child_id}/export.lyrapack",
        headers=headers,
        json={"copyright_confirmed": False},
    )
    assert pack_denied.status_code == 403

    pack_ok = client.post(
        f"/v1/arrangements/{child_id}/export.lyrapack",
        headers=headers,
        json={"copyright_confirmed": True, "license_notice": "Self-created test MIDI"},
    )
    assert pack_ok.status_code == 200
    assert pack_ok.content[:2] == b"PK"

    pack_imp = client.post(
        "/v1/imports/lyrapack",
        headers=headers,
        files={"file": ("shared.lyrapack", pack_ok.content, "application/zip")},
    )
    assert pack_imp.status_code == 200
    assert pack_imp.json()["song"]["title"] == "C Scale M3"

    backup_resp = client.get("/v1/library/backup.zip", headers=headers)
    assert backup_resp.status_code == 200
    assert backup_resp.content[:2] == b"PK"


def test_tools_status_and_background_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lyraforge.api import tool_service

    monkeypatch.setenv("LYRAFORGE_TOOLS_DIR", str(tmp_path / "tools"))
    app = create_app(data_dir=tmp_path / "tools_api", session_token="tools-token")
    headers = {SESSION_TOKEN_HEADER: "tools-token"}
    client = TestClient(app)

    listing = client.get("/v1/tools", headers=headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["tools_dir"] == str(tmp_path / "tools")
    assert {item["id"] for item in payload["tools"]} == {
        "ffmpeg",
        "basic-pitch",
        "dettato",
        "demucs",
        "swift-f0",
    }
    assert all(isinstance(item["installed"], bool) for item in payload["tools"])

    assert client.get("/v1/tools").status_code == 401
    assert client.post("/v1/tools/nope/install", headers=headers).status_code == 400

    def fake_install(tool_id: str, progress: object = None) -> dict[str, str]:
        if callable(progress):
            progress(0.5, "halfway")
            progress(1.0, "done")
        return {"id": tool_id}

    monkeypatch.setattr(tool_service, "install_tool", fake_install)
    started = client.post("/v1/tools/basic-pitch/install", headers=headers)
    assert started.status_code == 200
    assert started.json()["install"]["status"] in {"running", "installed"}

    deadline = time.time() + 5.0
    item: dict[str, object] = {}
    while time.time() < deadline:
        installs = client.get("/v1/tools", headers=headers).json()["installs"]
        item = next((i for i in installs if i["tool_id"] == "basic-pitch"), {})
        if item.get("status") == "installed":
            break
        time.sleep(0.05)
    assert item["status"] == "installed"
    assert item["progress"] == 1.0


def test_api_preview_arrange_and_created_flag(tmp_path: Path) -> None:
    token = "r32-tok"
    client = TestClient(create_app(data_dir=tmp_path / "r32_data", session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    # Import MIDI and check created flag + non-mutating live preview-arrange + transform payload
    chords_bytes = (FIXTURE_DIR / "chords_type1.mid").read_bytes()
    imp = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("chords_type1.mid", chords_bytes, "audio/midi")},
        data={"title": "R32 Chords"},
    )
    assert imp.status_code == 200
    song_id = imp.json()["song"]["id"]

    pv_new = client.post(
        "/v1/studio/preview-arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced"},
    )
    assert pv_new.status_code == 200
    assert pv_new.json()["already_exists"] is False
    assert len(pv_new.json()["performance"]["events"]) > 0
    # Ensure preview-arrange created zero DB rows
    assert client.get(f"/v1/library/songs/{song_id}", headers=headers).json()["arrangements"] == []

    first = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced", "arpeggiate_ms": 15},
    )
    assert first.status_code == 200
    assert first.json()["created"] is True
    arr_id = first.json()["arrangement"]["id"]

    detail = client.get(f"/v1/arrangements/{arr_id}", headers=headers).json()
    assert detail["report"]["transform"]["strategy"] == "balanced"
    assert detail["report"]["transform"]["arpeggiate_ms"] == 15
    assert detail["performance"]["transform"]["arpeggiate_ms"] == 15

    second = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced", "arpeggiate_ms": 15},
    )
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["arrangement"]["id"] == arr_id

    pv_existing = client.post(
        "/v1/studio/preview-arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced", "arpeggiate_ms": 15},
    )
    assert pv_existing.status_code == 200
    assert pv_existing.json()["already_exists"] is True
