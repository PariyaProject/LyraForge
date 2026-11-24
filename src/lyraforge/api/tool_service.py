"""Background installer state for the optional external toolchain."""

from __future__ import annotations

import threading
import time
from typing import Any

from lyraforge.errors import ErrorCode, LyraError
from lyraforge.toolchain import install as install_tool
from lyraforge.toolchain.specs import tool_ids


class ToolInstallManager:
    """Runs at most one install per tool and exposes progress for UI polling."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}

    def start(self, tool_id: str) -> dict[str, Any]:
        allowed_extra = ("dettato-gpu", "demucs-gpu")
        if tool_id not in tool_ids() and tool_id not in allowed_extra:
            raise LyraError(
                ErrorCode.INVALID_ARGUMENT,
                f"unknown tool: {tool_id!r}",
                {"available": [*tool_ids(), *allowed_extra]},
            )
        with self._lock:
            current = self._items.get(tool_id)
            if current is not None and current["status"] == "running":
                raise LyraError(
                    ErrorCode.LIBRARY_BUSY, f"{tool_id} is already being installed"
                )
            self._items[tool_id] = {
                "tool_id": tool_id,
                "status": "running",
                "progress": 0.0,
                "message": "准备安装…",
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }
        thread = threading.Thread(
            target=self._run,
            args=(tool_id,),
            name=f"tool-install-{tool_id}",
            daemon=True,
        )
        thread.start()
        return self.get(tool_id)

    def _run(self, tool_id: str) -> None:
        def progress(fraction: float, message: str) -> None:
            with self._lock:
                item = self._items.get(tool_id)
                if item is not None:
                    item["progress"] = round(max(0.0, min(1.0, fraction)), 3)
                    item["message"] = message

        try:
            install_tool(tool_id, progress)
        except LyraError as exc:
            error = f"[{exc.code}] {exc.message}"
        except Exception as exc:  # noqa: BLE001 - install must never take the server down
            error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                item = self._items.get(tool_id)
                if item is not None:
                    item.update(
                        status="installed",
                        progress=1.0,
                        message="安装完成",
                        finished_at=time.time(),
                    )
            return

        with self._lock:
            item = self._items.get(tool_id)
            if item is not None:
                item.update(
                    status="failed",
                    message="安装失败",
                    error=error,
                    finished_at=time.time(),
                )

    def get(self, tool_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._items.get(tool_id, {}))

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items.values()]
