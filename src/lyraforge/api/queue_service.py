"""Ordered playback queue shared by the desktop UI and global hotkeys."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from lyraforge.playback.factory import PlaybackMode


@dataclass(frozen=True, slots=True)
class QueueItem:
    arrangement_id: str
    label: str

    def to_json(self) -> dict[str, str]:
        return {"arrangement_id": self.arrangement_id, "label": self.label}


class PlaybackQueueManager:
    """A small ordered list with a current index; stepping wraps around."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[QueueItem] = []
        self._index = 0
        self._mode = PlaybackMode.DRY_RUN
        self._realtime = False

    def set_items(
        self,
        items: list[QueueItem],
        *,
        start_index: int = 0,
        mode: PlaybackMode = PlaybackMode.DRY_RUN,
        realtime: bool = False,
    ) -> None:
        with self._lock:
            self._items = list(items)
            self._index = max(0, min(int(start_index), max(0, len(items) - 1)))
            self._mode = PlaybackMode(mode)
            self._realtime = bool(realtime)

    def add(self, item: QueueItem) -> None:
        with self._lock:
            self._items.append(item)

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._index = 0

    def remove_arrangement(self, arrangement_id: str) -> bool:
        """Remove any queued entries matching ``arrangement_id`` while preserving cursor order."""
        with self._lock:
            if not self._items:
                return False
            current_item = self._items[self._index] if 0 <= self._index < len(self._items) else None
            kept: list[QueueItem] = []
            removed = False
            removed_before = 0
            for idx, item in enumerate(self._items):
                if item.arrangement_id == arrangement_id:
                    removed = True
                    if idx < self._index:
                        removed_before += 1
                    continue
                kept.append(item)
            if not removed:
                return False
            self._items = kept
            if not kept:
                self._index = 0
            elif current_item is not None and current_item.arrangement_id != arrangement_id:
                self._index = max(0, min(self._index - removed_before, len(kept) - 1))
            else:
                self._index = max(0, min(self._index - removed_before, len(kept) - 1))
            return True

    def current(self) -> QueueItem | None:
        with self._lock:
            if not self._items:
                return None
            return self._items[self._index]

    def step(self, delta: int) -> QueueItem | None:
        """Move the index and return the new current item (wraps around)."""
        with self._lock:
            if not self._items:
                return None
            self._index = (self._index + int(delta)) % len(self._items)
            return self._items[self._index]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "items": [item.to_json() for item in self._items],
                "index": self._index,
                "mode": str(self._mode),
                "realtime": self._realtime,
            }


__all__ = ["PlaybackQueueManager", "QueueItem"]
