"""Persistent settings, stored as JSON next to the user's other app config."""

from __future__ import annotations

import json
import threading
from typing import Any

from .paths import config_file

# Guard rails for the interval spinner. One second is pointless churn, an hour
# is longer than any lock timeout worth defending against.
MIN_INTERVAL = 5
MAX_INTERVAL = 3600


class Config:
    """Thread-safe settings store with atomic writes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "theme": "dark",
            "master_active": False,
            "start_minimized": False,
            "geometry": None,
            "log_expanded": False,
            "techniques": {},
        }
        self.load()

    # ---------------------------------------------------------------- io

    def load(self) -> None:
        path = config_file()
        if not path.exists():
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt config must never stop the app from starting.
            return
        if isinstance(loaded, dict):
            with self._lock:
                self._data.update(loaded)
                self._data.setdefault("techniques", {})

    def save(self) -> None:
        path = config_file()
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            payload = json.dumps(self._data, indent=2, sort_keys=True)
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    # ------------------------------------------------------------ access

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    # --------------------------------------------------------- per technique

    def technique(self, tech_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["techniques"].get(tech_id, {}))

    def is_enabled(self, tech_id: str, default: bool = False) -> bool:
        return bool(self.technique(tech_id).get("enabled", default))

    def interval(self, tech_id: str, default: int) -> int:
        value = self.technique(tech_id).get("interval", default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return max(MIN_INTERVAL, min(MAX_INTERVAL, value))

    def set_enabled(self, tech_id: str, enabled: bool) -> None:
        with self._lock:
            entry = self._data["techniques"].setdefault(tech_id, {})
            entry["enabled"] = bool(enabled)

    def set_interval(self, tech_id: str, seconds: int) -> None:
        seconds = max(MIN_INTERVAL, min(MAX_INTERVAL, int(seconds)))
        with self._lock:
            entry = self._data["techniques"].setdefault(tech_id, {})
            entry["interval"] = seconds
