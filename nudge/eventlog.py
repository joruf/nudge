"""In-memory ring buffer of what the scheduler did, shown in the UI log panel."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from .i18n import Msg

Level = Literal["info", "ok", "warn", "error"]
Text = Msg | str


@dataclass(frozen=True)
class Entry:
    timestamp: float
    level: Level
    source: Text
    message: Text

    def clock(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))

    # Entries keep deferred messages, so switching language also relabels
    # everything that was logged earlier in the session.
    def source_text(self) -> str:
        return str(self.source)

    def text(self) -> str:
        return str(self.message)


class EventLog:
    def __init__(self, capacity: int = 300) -> None:
        self._lock = threading.Lock()
        self._entries: list[Entry] = []
        self._capacity = capacity
        self._revision = 0

    def add(self, level: Level, source: Text, message: Text) -> None:
        with self._lock:
            self._entries.append(Entry(time.time(), level, source, message))
            if len(self._entries) > self._capacity:
                del self._entries[: len(self._entries) - self._capacity]
            self._revision += 1

    def info(self, source: Text, message: Text) -> None:
        self.add("info", source, message)

    def ok(self, source: Text, message: Text) -> None:
        self.add("ok", source, message)

    def warn(self, source: Text, message: Text) -> None:
        self.add("warn", source, message)

    def error(self, source: Text, message: Text) -> None:
        self.add("error", source, message)

    def revision(self) -> int:
        """Cheap change token so the UI can skip redrawing an unchanged log."""
        with self._lock:
            return self._revision

    def bump(self) -> None:
        """Force the next redraw, e.g. after the language changed."""
        with self._lock:
            self._revision += 1

    def tail(self, count: int = 120) -> list[Entry]:
        with self._lock:
            return self._entries[-count:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._revision += 1
