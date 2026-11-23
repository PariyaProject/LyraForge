"""Tests for the playback queue (manager and HTTP endpoints)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.api.queue_service import PlaybackQueueManager, QueueItem

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_queue_manager_wraps_and_clears() -> None:
    queue = PlaybackQueueManager()
    assert queue.snapshot()["items"] == []
    assert queue.step(1) is None

    queue.set_items(
        [QueueItem("a", "Song A · balanced"), QueueItem("b", "Song B · melody")],
        start_index=0,
    )
    assert queue.current() is not None
    assert queue.current().arrangement_id == "a"
    assert queue.step(1).arrangement_id == "b"
    assert queue.step(1).arrangement_id == "a"  # wraps
    assert queue.step(-1).arrangement_id == "b"

    queue.clear()
    assert queue.snapshot()["items"] == []


def test_queue_api_set_step_add_and_clear(tmp_path: Path) -> None:
    token = "queue-token"
    client = TestClient(create_app(data_dir=tmp_path / "queue_data", session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    midi_bytes = (FIXTURE_DIR / "c_major_scale.mid").read_bytes()
    imported = client.post(
        "/v1/imports",
        headers=headers,
        files={"file": ("c.mid", midi_bytes, "audio/midi")},
    )
    assert imported.status_code == 200
    song_id = imported.json()["song"]["id"]

    arrangement_ids: list[str] = []
    for style in ("balanced", "melody"):
        arranged = client.post(
            "/v1/jobs/arrange",
            headers=headers,
            json={"song_id": song_id, "style": style},
        )
        assert arranged.status_code == 200
        arrangement_ids.append(arranged.json()["arrangement"]["id"])

    set_resp = client.post(
        "/v1/playback/queue",
        headers=headers,
        json={"arrangement_ids": arrangement_ids, "mode": "dry-run"},
    )
    assert set_resp.status_code == 200
    queue = set_resp.json()
    assert len(queue["items"]) == 2
    assert queue["index"] == 0

    stepped = client.post(
        "/v1/playback/queue/step", headers=headers, json={"delta": 1}
    )
    assert stepped.status_code == 200
    assert stepped.json()["queue"]["index"] == 1
    assert stepped.json()["playback"]["status"] in {"running", "waiting_focus", "completed"}

    added = client.post(
        "/v1/playback/queue/add",
        headers=headers,
        json={"arrangement_id": arrangement_ids[0]},
    )
    assert added.status_code == 200
    assert len(added.json()["items"]) == 3

    cleared = client.post("/v1/playback/queue/clear", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["items"] == []
    client.post("/v1/playback/stop", headers=headers)
