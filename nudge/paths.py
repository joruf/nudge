"""Platform-appropriate locations for config and logs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID, APP_NAME

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def config_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    elif IS_MACOS:
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
        path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.json"


def platform_key() -> str:
    if IS_WINDOWS:
        return "windows"
    if IS_MACOS:
        return "macos"
    if IS_LINUX:
        return "linux"
    return sys.platform
