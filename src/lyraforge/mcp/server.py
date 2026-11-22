"""Minimal zero-dependency stdio JSON-RPC 2.0 server for Model Context Protocol (MCP)."""

from __future__ import annotations

import contextlib
import json
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from lyraforge import __version__
from lyraforge.library.store import LibraryStore
from lyraforge.mcp.tools import MCPToolExecutor
from lyraforge.playback.guards import StopToken
from lyraforge.secrets import redact_secret

SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")
DEFAULT_MCP_MAX_WORKERS = 4
DEFAULT_MCP_MAX_PENDING = 16


@dataclass(frozen=True, slots=True)
class _ToolCallDispatch:
    req_id: str | int | None
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _RoutedMessage:
    response: dict[str, Any] | None = None
    dispatch: _ToolCallDispatch | None = None


def _format_tool_response(
    req_id: Any, payload: dict[str, Any], is_error: bool
) -> dict[str, Any]:
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


class LyraMCPServer:
    """Line-delimited JSON-RPC 2.0 MCP server operating on stdin/stdout."""

    def __init__(
        self,
        executor: MCPToolExecutor,
        *,
        max_workers: int = DEFAULT_MCP_MAX_WORKERS,
        max_pending: int = DEFAULT_MCP_MAX_PENDING,
        shutdown_timeout_s: float = 10.0,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_pending < max_workers:
            raise ValueError("max_pending must be >= max_workers")
        self.executor = executor
        self._max_workers = max_workers
        self._max_pending = max_pending
        self._shutdown_timeout_s = max(0.05, float(shutdown_timeout_s))
        self._state_lock = threading.Lock()
        self._initialized = False
        self._active_req_tokens: dict[str, StopToken] = {}

    def _cancel_target(self, target_id: str) -> None:
        with self._state_lock:
            tok = self._active_req_tokens.get(target_id)
            if tok is not None:
                tok.request_stop(f"cancelled via MCP ({target_id})")
        self.executor.tasks.cancel(target_id)

    def _parse_and_route(self, raw_line: str) -> _RoutedMessage:
        text = raw_line.strip()
        if not text:
            return _RoutedMessage()
        try:
            msg = json.loads(text)
        except json.JSONDecodeError as exc:
            return _RoutedMessage(
                response={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
            )
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _RoutedMessage(
                response={
                    "jsonrpc": "2.0",
                    "id": msg.get("id") if isinstance(msg, dict) else None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            )

        is_notification = "id" not in msg
        req_id = msg.get("id")
        if not is_notification and (
            isinstance(req_id, bool)
            or (req_id is not None and not isinstance(req_id, (str, int)))
        ):
            return _RoutedMessage(
                response={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: bad 'id' type"},
                }
            )

        method = msg.get("method")
        if not isinstance(method, str) or not method.strip():
            return _RoutedMessage(
                response=(
                    None
                    if is_notification
                    else {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32600, "message": "Invalid Request: missing 'method'"},
                    }
                )
            )
        method = method.strip()

        if "params" in msg:
            raw_params = msg["params"]
            if not isinstance(raw_params, dict):
                return _RoutedMessage(
                    response=(
                        None
                        if is_notification
                        else {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32602, "message": "params must be a JSON object"},
                        }
                    )
                )
            params = raw_params
        else:
            params = {}

        if is_notification:
            self._handle_notification(method, params)
            return _RoutedMessage()

        if method == "initialize":
            raw_ver = params.get("protocolVersion")
            if raw_ver is not None and not isinstance(raw_ver, str):
                return _RoutedMessage(
                    response={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32602,
                            "message": "initialize 'protocolVersion' must be a string",
                        },
                    }
                )
            req_ver = raw_ver or ""
            proto = (
                req_ver
                if req_ver in SUPPORTED_PROTOCOL_VERSIONS
                else SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            with self._state_lock:
                self._initialized = True
            return _RoutedMessage(
                response={
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
                            "LyraForge local music arrangement MCP tools. Offline features require "
                            "no API key. play_in_game is gated behind desktop interactive "
                            "confirmation and cannot trigger OS key simulation directly."
                        ),
                    },
                }
            )

        if method == "ping":
            return _RoutedMessage(response={"jsonrpc": "2.0", "id": req_id, "result": {}})

        if method == "tools/list":
            with self._state_lock:
                is_init = self._initialized
            if not is_init:
                return _RoutedMessage(
                    response={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32002,
                            "message": "Server not initialized; call 'initialize' first",
                        },
                    }
                )
            return _RoutedMessage(
                response={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": self.executor.list_tools()},
                }
            )

        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name.strip():
                return _RoutedMessage(
                    response={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32602, "message": "tools/call requires string 'name'"},
                    }
                )
            if "arguments" in params:
                arguments = params["arguments"]
                if not isinstance(arguments, dict):
                    return _RoutedMessage(
                        response={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32602,
                                "message": "tools/call 'arguments' must be a JSON object",
                            },
                        }
                    )
            else:
                arguments = {}

            with self._state_lock:
                is_init = self._initialized
            if not is_init:
                return _RoutedMessage(
                    response={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32002,
                            "message": "Server not initialized; call 'initialize' first",
                        },
                    }
                )

            return _RoutedMessage(
                dispatch=_ToolCallDispatch(
                    req_id=req_id,
                    tool_name=name.strip(),
                    arguments=dict(arguments),
                )
            )

        return _RoutedMessage(
            response={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )

    def handle_message(self, raw_line: str) -> dict[str, Any] | None:
        routed = self._parse_and_route(raw_line)
        if routed.dispatch is None:
            return routed.response
        d = routed.dispatch
        tok = StopToken()
        if d.req_id is not None and self.executor.tasks.is_pre_cancelled(str(d.req_id)):
            tok.request_stop(f"cancelled via MCP ({d.req_id})")
        payload, is_error = self.executor.call(
            d.tool_name,
            d.arguments,
            request_id=d.req_id,
            stop_token=tok,
        )
        return _format_tool_response(d.req_id, payload, is_error)

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "notifications/initialized":
            with self._state_lock:
                self._initialized = True
        elif method == "notifications/cancelled":
            if "requestId" in params and params["requestId"] is not None:
                target: Any = params["requestId"]
            else:
                target = params.get("taskId")
            if target is not None and not isinstance(target, (bool, list, dict)):
                self._cancel_target(str(target))

    def serve_streams(self, stdin: TextIO, stdout: TextIO) -> int:
        write_lock = threading.Lock()
        active_futures: set[Future[None]] = set()
        disconnected = threading.Event()

        def _cancel_all_inflight(reason: str) -> None:
            with self._state_lock:
                for tok in self._active_req_tokens.values():
                    tok.request_stop(reason)
                queued = list(active_futures)
            for fut in queued:
                fut.cancel()
            self.executor.tasks.cancel_all(reason)

        def _emit(payload: dict[str, Any]) -> None:
            if disconnected.is_set():
                return
            raw = json.dumps(payload, ensure_ascii=False) + "\n"
            try:
                with write_lock:
                    stdout.write(raw)
                    stdout.flush()
            except (BrokenPipeError, OSError, ValueError):
                disconnected.set()
                _cancel_all_inflight("client_disconnected")

        def _run_tool_call(dispatch: _ToolCallDispatch, req_token: StopToken) -> None:
            try:
                payload, is_error = self.executor.call(
                    dispatch.tool_name,
                    dispatch.arguments,
                    request_id=dispatch.req_id,
                    stop_token=req_token,
                )
                _emit(_format_tool_response(dispatch.req_id, payload, is_error))
            except Exception as exc:  # noqa: BLE001
                secret_val = ""
                with contextlib.suppress(Exception):
                    secret_val = self.executor.store._secrets.get("llm_api_key") or ""
                _emit(
                    {
                        "jsonrpc": "2.0",
                        "id": dispatch.req_id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {redact_secret(str(exc), (secret_val,))}",
                        },
                    }
                )

        pool = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="lyraforge-mcp"
        )
        try:
            for line in stdin:
                if disconnected.is_set():
                    break
                routed = self._parse_and_route(line)
                if routed.response is not None:
                    _emit(routed.response)
                    continue
                if routed.dispatch is None:
                    continue

                dispatch = routed.dispatch
                overloaded = False
                req_key = str(dispatch.req_id) if dispatch.req_id is not None else None
                req_token = StopToken()

                with self._state_lock:
                    done_refs = [f for f in active_futures if f.done()]
                    for df in done_refs:
                        active_futures.discard(df)
                    if len(active_futures) >= self._max_pending:
                        overloaded = True
                    else:
                        if req_key is not None and self.executor.tasks.is_pre_cancelled(req_key):
                            req_token.request_stop(f"cancelled via MCP ({req_key})")
                        raw_tid = dispatch.arguments.get("task_id")
                        if (
                            isinstance(raw_tid, str)
                            and raw_tid.strip()
                            and self.executor.tasks.is_pre_cancelled(raw_tid.strip())
                        ):
                            req_token.request_stop(f"cancelled via MCP ({raw_tid.strip()})")
                        if req_key is not None:
                            self._active_req_tokens[req_key] = req_token
                        fut = pool.submit(_run_tool_call, dispatch, req_token)
                        active_futures.add(fut)

                        def _on_done(
                            done_fut: Future[None],
                            rk: str | None = req_key,
                            tok: StopToken = req_token,
                        ) -> None:
                            with self._state_lock:
                                active_futures.discard(done_fut)
                                if rk is not None and self._active_req_tokens.get(rk) is tok:
                                    self._active_req_tokens.pop(rk, None)
                                    self.executor.tasks.consume_pre_cancel(rk)

                        fut.add_done_callback(_on_done)

                if overloaded:
                    _emit(
                        {
                            "jsonrpc": "2.0",
                            "id": dispatch.req_id,
                            "error": {
                                "code": -32001,
                                "message": (
                                    "Server overloaded: too many pending MCP tool requests "
                                    f"(limit={self._max_pending})"
                                ),
                                "data": {"max_pending": self._max_pending},
                            },
                        }
                    )
        finally:
            with self._state_lock:
                remaining = [f for f in active_futures if not f.done()]
            if remaining and not disconnected.is_set():
                _done, not_done = wait(remaining, timeout=self._shutdown_timeout_s)
                if not_done:
                    _cancel_all_inflight("shutdown_timeout")
                    wait(not_done, timeout=min(2.0, max(0.5, self._shutdown_timeout_s)))
            elif remaining:
                _cancel_all_inflight("client_disconnected")
                wait(remaining, timeout=min(2.0, max(0.5, self._shutdown_timeout_s)))

            with self._state_lock:
                for tok in self._active_req_tokens.values():
                    tok.request_stop("server_shutdown")
                self._active_req_tokens.clear()
                active_futures.clear()
            pool.shutdown(wait=False, cancel_futures=True)
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
