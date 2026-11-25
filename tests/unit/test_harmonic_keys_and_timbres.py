"""Unit and integration tests for Harmonic Keys default instrument and multi-timbre preview."""

from __future__ import annotations

import io
import json
import math
import wave
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import create_app
from lyraforge.api.app import SESSION_TOKEN_HEADER
from lyraforge.cli import main as cli_main
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.instruments import DEFAULT_PROFILE_ID, list_profile_ids, load_builtin_profile
from lyraforge.library.store import LibraryStore
from lyraforge.mcp import LyraMCPServer, MCPTaskRegistry, MCPToolExecutor
from lyraforge.music_core.arranger import arrange
from lyraforge.music_core.midi_import import load_midi_file
from lyraforge.music_core.performance import build_performance
from lyraforge.presets import list_presets
from lyraforge.preview import (
    VALID_TIMBRES,
    resolve_timbre,
    synthesize_performance,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_harmonic_keys_is_default_21_key_profile_with_presets() -> None:
    assert DEFAULT_PROFILE_ID == "genshin.harmonic_keys.v1"
    ids = list_profile_ids()
    assert ids[0] == "genshin.harmonic_keys.v1"
    assert {
        "genshin.windsong_lyre.v1",
        "genshin.floral_zither.v1",
        "genshin.vintage_lyre.v1",
    } <= set(ids)

    hk = load_builtin_profile("genshin.harmonic_keys.v1")
    windsong = load_builtin_profile("genshin.windsong_lyre.v1")
    assert hk.display_name == "谐律键琴"
    assert hk.raw["display_name_en"] == "Harmonic Keys"
    assert len(hk.keys) == 21
    assert [(k.key_id, k.pitch, k.binding) for k in hk.keys] == [
        (k.key_id, k.pitch, k.binding) for k in windsong.keys
    ]
    assert len(list_presets("genshin.harmonic_keys.v1")) == 5


def test_resolve_timbre_and_distinct_wav_synthesis() -> None:
    assert resolve_timbre("genshin.harmonic_keys.v1", "auto") == "piano"
    assert resolve_timbre("genshin.windsong_lyre.v1", "auto") == "lyre"
    assert resolve_timbre("genshin.floral_zither.v1", "auto") == "zither"
    assert resolve_timbre("genshin.vintage_lyre.v1", "auto") == "vintage"
    assert resolve_timbre("genshin.harmonic_keys.v1", "lyre") == "lyre"

    with pytest.raises(LyraError) as exc_info:
        resolve_timbre("genshin.harmonic_keys.v1", "banjo")
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENT

    score = load_midi_file(FIXTURE_DIR / "c_major_scale.mid")
    profile = load_builtin_profile("genshin.harmonic_keys.v1")
    perf = build_performance(score, profile, arrange(score, profile))

    wavs = {
        t: synthesize_performance(perf, timbre=t)
        for t in ("piano", "lyre", "zither", "vintage")
    }
    assert len(set(wavs.values())) == 4
    # Auto timbre on harmonic_keys matches explicit piano timbre
    assert synthesize_performance(perf, timbre="auto") == wavs["piano"]

    # Piano tails ring noticeably longer than lyre/vintage so WAV duration differs
    def _frames(raw: bytes) -> int:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            return wf.getnframes()

    assert math.isclose(_frames(wavs["piano"]), _frames(wavs["piano"]), rel_tol=1e-6)
    assert _frames(wavs["piano"]) > _frames(wavs["lyre"])
    assert set(VALID_TIMBRES) == {"auto", "piano", "lyre", "zither", "vintage"}


def test_timbre_preview_api_cache_cleanup_cli_and_mcp_parity(tmp_path: Path) -> None:
    data_dir = tmp_path / "timbre_data"
    token = "timbre-tok"
    app = create_app(data_dir=data_dir, session_token=token)
    headers = {SESSION_TOKEN_HEADER: token}
    client = TestClient(app)

    mid_path = FIXTURE_DIR / "c_major_scale.mid"
    with mid_path.open("rb") as fh:
        imp = client.post(
            "/v1/imports",
            headers=headers,
            files={"file": ("c_major_scale.mid", fh, "audio/midi")},
            data={"title": "Harmonic Scale"},
        ).json()
    song_id = imp["song"]["id"]

    # Default arrangement uses genshin.harmonic_keys.v1
    arr_res = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "balanced"},
    )
    assert arr_res.status_code == 200
    arr = arr_res.json()["arrangement"]
    assert arr["profile_id"] == "genshin.harmonic_keys.v1"
    arr_id = arr["id"]

    # Explicit timbre=zither + fixed_velocity=True caches separately and downloads WAV cleanly
    p_z = client.post(
        "/v1/preview",
        headers=headers,
        json={"arrangement_id": arr_id, "fixed_velocity": True, "timbre": "zither"},
    )
    assert p_z.status_code == 200
    p_json = p_z.json()
    assert p_json["timbre"] == "zither"
    assert "timbre=zither" in p_json["preview_url"]
    assert "fixed_velocity=1" in p_json["preview_url"]

    cached_file = data_dir / "songs" / song_id / "previews" / f"{arr_id}.zither.fixed.wav"
    assert cached_file.is_file()
    wav_get = client.get(p_json["preview_url"], headers=headers)
    assert wav_get.status_code == 200
    assert wav_get.content[:4] == b"RIFF"

    # Arrangement deletion removes extra timbre cache files
    assert client.delete(f"/v1/arrangements/{arr_id}", headers=headers).status_code == 200
    assert not cached_file.exists()

    # Re-create an arrangement for CLI & MCP preview --timbre checks
    arr_id2 = client.post(
        "/v1/jobs/arrange",
        headers=headers,
        json={"song_id": song_id, "style": "melody"},
    ).json()["arrangement"]["id"]

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["preview", arr_id2, "--data-dir", str(data_dir), "--timbre", "piano"])
    assert rc == 0
    cli_payload = json.loads(buf.getvalue())
    assert cli_payload["timbre"] == "piano"
    assert cli_payload["wav_path"].endswith(".piano.wav")

    with LibraryStore(data_dir) as store:
        server = LyraMCPServer(MCPToolExecutor(store, tasks=MCPTaskRegistry()))
        server.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "1.0"},
                    },
                }
            )
        )
        server.handle_message(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        mcp_prev = server.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "preview",
                        "arguments": {"arrangement_id": arr_id2, "timbre": "vintage"},
                    },
                }
            )
        )
        assert mcp_prev is not None and "result" in mcp_prev
        mcp_data = json.loads(mcp_prev["result"]["content"][0]["text"])
        assert mcp_data["timbre"] == "vintage"
        assert mcp_data["wav_path"].endswith(".vintage.wav")
