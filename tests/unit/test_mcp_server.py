"""Unit and real stdio subprocess integration tests for LyraForge MCP server."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from lyraforge.library.store import LibraryStore
from lyraforge.mcp import LyraMCPServer, MCPTaskRegistry, MCPToolExecutor
from lyraforge.secrets import MemorySecretBackend, SecretStore

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "midi"


def test_mcp_protocol_errors_cancellation_and_redaction(tmp_path: Path) -> None:
    sec_backend = MemorySecretBackend({"llm_api_key": "sk-super-secret-xyz99"})
    secrets = SecretStore(primary=sec_backend, fallback=None)
    with LibraryStore(tmp_path / "lib", secret_store=secrets) as store:
        registry = MCPTaskRegistry()
        executor = MCPToolExecutor(store, tasks=registry)
        server = LyraMCPServer(executor)

        # Invalid JSON / Request / Method / Params
        bad_json = server.handle_message("{not-json")
        assert bad_json is not None and bad_json["error"]["code"] == -32700

        bad_req = server.handle_message(json.dumps({"jsonrpc": "1.0"}))
        assert bad_req is not None and bad_req["error"]["code"] == -32600

        bad_method = server.handle_message(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "nope"})
        )
        assert bad_method is not None and bad_method["error"]["code"] == -32601

        bad_call = server.handle_message(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {}})
        )
        assert bad_call is not None and bad_call["error"]["code"] == -32602

        # Notification must not emit a response
        assert (
            server.handle_message(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            )
            is None
        )

        # Ping
        pong = server.handle_message(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}))
        assert pong == {"jsonrpc": "2.0", "id": 3, "result": {}}

        # Unknown tool -> structured MCP tool error
        unknown = server.handle_message(
            json.dumps({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
            })
        )
        assert unknown is not None
        assert unknown["result"]["isError"] is True
        assert unknown["result"]["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

        # Error messages must redact stored secrets
        payload, is_err = executor.call(
            "import_media",
            {"path": str(tmp_path / "sk-super-secret-xyz99.mid")},
        )
        assert is_err is True
        assert "sk-super-secret-xyz99" not in json.dumps(payload)

        # Network & rights gating
        net_blocked, err_net = executor.call(
            "import_media",
            {"url": "https://93.184.216.34/song.mid", "allow_network": False},
        )
        assert err_net is True
        assert net_blocked["error"]["code"] == "PERMISSION_REQUIRED"

        # Task registry & notification cancellation
        task = registry.create("transcribe", task_id="task-cancel-demo", request_id=77)
        registry.log(task.task_id, 0.5, "working")
        assert (
            server.handle_message(
                json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 77},
                })
            )
            is None
        )
        snap, snap_err = executor.call("get_task_status", {"task_id": "task-cancel-demo"})
        assert snap_err is False
        assert snap["task"]["status"] == "cancelled"
        assert task.stop_token.stopped is True


def test_mcp_stdio_subprocess_end_to_end(tmp_path: Path) -> None:
    data_dir = tmp_path / "mcp_data"
    midi_src = FIXTURE_DIR / "c_major_scale.mid"
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    lyrapack_out = export_dir / "scale.lyrapack"
    midi_out = export_dir / "scale_arr.mid"
    wav_out = export_dir / "scale_preview.wav"

    proc = subprocess.Popen(
        [sys.executable, "-m", "lyraforge.cli", "mcp", "--data-dir", str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None

    def rpc(req_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            err_out = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"MCP subprocess closed stdout prematurely; stderr={err_out}")
        return dict(json.loads(line))

    def call_tool(req_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resp = rpc(req_id, "tools/call", {"name": name, "arguments": arguments})
        assert "result" in resp, f"unexpected RPC error for {name}: {resp}"
        return dict(resp["result"])

    try:
        init_res = rpc(
            1,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest-mcp", "version": "1.0"},
            },
        )
        assert init_res["result"]["serverInfo"]["name"] == "lyraforge"
        assert init_res["result"]["protocolVersion"] == "2025-03-26"

        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        proc.stdin.flush()

        tools_res = rpc(2, "tools/list")
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        assert {
            "search_music",
            "import_media",
            "transcribe",
            "arrange",
            "evaluate",
            "preview",
            "save_to_library",
            "export_score",
            "get_task_status",
            "play_in_game",
        }.issubset(tool_names)

        # Import MIDI -> search -> arrange -> evaluate -> preview -> save -> export -> gate playback
        imp = call_tool(
            3, "import_media", {"path": str(midi_src), "title": "MCP C Scale", "artist": "Pytest"}
        )
        assert imp["isError"] is False
        song_id = imp["structuredContent"]["song"]["id"]

        srch = call_tool(4, "search_music", {"query": "MCP C Scale", "allow_network": False})
        assert srch["isError"] is False
        assert srch["structuredContent"]["candidates"][0]["license_status"] == "user_local"

        arr = call_tool(
            5,
            "arrange",
            {"song_id": song_id, "profile_id": "genshin.windsong_lyre.v1", "style": "balanced"},
        )
        assert arr["isError"] is False
        arr_id = arr["structuredContent"]["arrangement"]["id"]
        assert (
            arr["structuredContent"]["arrangement_playability_vs_input_midi"]["quality"][
                "score_scope"
            ]
            == "arrangement_vs_input_midi"
        )

        ev = call_tool(
            6,
            "evaluate",
            {"arrangement_id": arr_id, "reference_midi_path": str(midi_src)},
        )
        assert ev["isError"] is False
        assert ev["structuredContent"]["end_to_end_vs_reference"]["reference_pitch_recall"] == 1.0

        prv = call_tool(7, "preview", {"arrangement_id": arr_id, "output_path": str(wav_out)})
        assert prv["isError"] is False
        assert wav_out.is_file() and wav_out.stat().st_size > 100

        saved = call_tool(
            8,
            "save_to_library",
            {
                "song_id": song_id,
                "tags": ["mcp", "demo"],
                "arrangement_id": arr_id,
                "label": "Verified via MCP",
                "is_favorite": True,
                "user_vote": 1,
            },
        )
        assert saved["isError"] is False
        assert saved["structuredContent"]["arrangement"]["is_favorite"] is True

        blocked_pack = call_tool(
            9,
            "export_score",
            {
                "arrangement_id": arr_id,
                "format": "lyrapack",
                "output_path": str(lyrapack_out),
                "rights_confirmed": False,
            },
        )
        assert blocked_pack["isError"] is True
        assert blocked_pack["structuredContent"]["error"]["code"] == "PERMISSION_REQUIRED"

        ok_midi = call_tool(
            10,
            "export_score",
            {"arrangement_id": arr_id, "format": "midi", "output_path": str(midi_out)},
        )
        assert ok_midi["isError"] is False and midi_out.is_file()

        ok_pack = call_tool(
            11,
            "export_score",
            {
                "arrangement_id": arr_id,
                "format": "lyrapack",
                "output_path": str(lyrapack_out),
                "rights_confirmed": True,
            },
        )
        assert ok_pack["isError"] is False and lyrapack_out.is_file()
        with zipfile.ZipFile(lyrapack_out, "r") as zf:
            assert all(not n.endswith(".wav") for n in zf.namelist())

        # Transcribe flow using the rendered WAV preview
        imp_wav = call_tool(12, "import_media", {"path": str(wav_out), "title": "MCP WAV"})
        wav_song_id = imp_wav["structuredContent"]["song"]["id"]
        tr = call_tool(13, "transcribe", {"song_id": wav_song_id, "engine_id": "builtin-mono"})
        assert tr["isError"] is False
        task_id = tr["structuredContent"]["task_id"]

        tasks_res = call_tool(14, "get_task_status", {"task_id": task_id})
        assert tasks_res["isError"] is False
        assert tasks_res["structuredContent"]["task"]["status"] == "completed"

        # Sensitive action play_in_game must remain gated and never send keystrokes
        play = call_tool(15, "play_in_game", {"arrangement_id": arr_id})
        assert play["isError"] is False
        assert play["structuredContent"]["executed"] is False
        assert play["structuredContent"]["status"] == "blocked_requires_interactive_confirmation"
        assert play["structuredContent"]["requires_user_confirmation"] is True
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise
        assert rc == 0
