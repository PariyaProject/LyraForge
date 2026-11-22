"""Minimal zero-dependency stdio JSON-RPC 2.0 server for Model Context Protocol (MCP)."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO

from lyraforge import __version__
from lyraforge.library.store import LibraryStore
from lyraforge.mcp.tools import MCPToolExecutor

SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")


class LyraMCPServer:
    """Line-delimited JSON-RPC 2.0 MCP server operating on stdin/stdout."""

    def __init__(self, executor: MCPToolExecutor) -> None:
        self.executor = executor
        self._initialized = False

    def handle_message(self, raw_line: str) -> dict[str, Any] | None:
        text = raw_line.strip()
        if not text:
            return None
        try:
            msg = json.loads(text)
        except json.JSONDecodeError as exc:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return {
                "jsonrpc": "2.0",
                "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }

        req_id = msg.get("id")
        is_notification = "id" not in msg
        method = str(msg.get("method") or "")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

        if is_notification:
            self._handle_notification(method, params)
            return None

        if method == "initialize":
            req_ver = str(params.get("protocolVersion") or "")
            proto = (
                req_ver
                if req_ver in SUPPORTED_PROTOCOL_VERSIONS
                else SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            self._initialized = True
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": proto,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "lyraforge",
                        "version": __version__,
                    },
                    "instructions": (
                        "LyraForge local music arrangement MCP tools. Offline features require no "
                        "API key. play_in_game is gated behind desktop interactive confirmation "
                        "and cannot trigger OS key simulation directly."
                    ),
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.executor.list_tools()},
            }

        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name.strip():
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "tools/call requires string 'name'"},
                }
            arguments = params.get("arguments")
            payload, is_error = self.executor.call(
                name.strip(),
                arguments if isinstance(arguments, dict) else {},
                request_id=req_id,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False),
                        }
                    ],
                    "structuredContent": payload,
                    "isError": is_error,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "notifications/initialized":
            self._initialized = True
        elif method == "notifications/cancelled":
            target = params.get("requestId") or params.get("taskId")
            if target is not None:
                self.executor.tasks.cancel(str(target))

    def serve_streams(self, stdin: TextIO, stdout: TextIO) -> int:
        write_lock = threading.Lock()

        def _emit(payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False) + "\n"
            with write_lock:
                stdout.write(raw)
                stdout.flush()

        def _run_tool_call(req_id: Any, tool_name: str, arguments: dict[str, Any]) -> None:
            payload, is_error = self.executor.call(
                tool_name,
                arguments,
                request_id=req_id,
            )
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            }
                        ],
                        "structuredContent": payload,
                        "isError": is_error,
                    },
                }
            )

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="lyraforge-mcp") as pool:
            pending: list[Future[None]] = []
            for line in stdin:
                text = line.strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    resp = self.handle_message(line)
                    if resp is not None:
                        _emit(resp)
                    continue
                if (
                    isinstance(msg, dict)
                    and msg.get("jsonrpc") == "2.0"
                    and "id" in msg
                    and msg.get("method") == "tools/call"
                    and isinstance(msg.get("params"), dict)
                    and isinstance(msg["params"].get("name"), str)
                    and msg["params"]["name"].strip()
                ):
                    params = msg["params"]
                    arguments = params.get("arguments")
                    fut = pool.submit(
                        _run_tool_call,
                        msg.get("id"),
                        params["name"].strip(),
                        arguments if isinstance(arguments, dict) else {},
                    )
                    pending.append(fut)
                    continue
                resp = self.handle_message(line)
                if resp is not None:
                    _emit(resp)
            for fut in pending:
                fut.result()
        return 0


def run_stdio_server(
    *,
    data_dir: str | Path | None = None,
    search_dirs: Sequence[str | Path] = (),
    allow_network: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Start the LyraForge MCP server over standard input/output."""
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    for stream in (in_stream, out_stream):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with LibraryStore(data_dir) as store:
        executor = MCPToolExecutor(
            store,
            search_dirs=search_dirs,
            default_allow_network=allow_network,
        )
        server = LyraMCPServer(executor)
        return server.serve_streams(in_stream, out_stream)
