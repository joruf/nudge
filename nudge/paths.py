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


# --- installation layout ------------------------------------------------------------------------
# Nudge runs from a clone rather than an installation, so everything it needs is found relative to
# the package. Nudge.desktop in the project root is the launcher: it starts the program by
# double-click, and it doubles as the template for the copies that go into the application menu and
# the autostart directory. resources/ holds the icons rendered on first start (see
# ui/window_icon.py), which are not in version control.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources"

DESKTOP_LAUNCHER = PROJECT_ROOT / f"{APP_NAME}.desktop"
DESKTOP_FILENAME = f"{APP_ID}.desktop"
ICON_BASENAME = APP_ID

#: Windows gets the .pyw launcher, because pythonw.exe opens no console for it.
LAUNCHER_SCRIPT = PROJECT_ROOT / ("nudge.pyw" if IS_WINDOWS else "nudge.py")


def cache_dir() -> Path:
    """Where generated files go when the program directory is read-only."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "cache"
    if IS_MACOS:
        return Path.home() / "Library" / "Caches" / APP_NAME
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / APP_ID


def data_dir() -> Path:
    """The user's own share of the desktop file hierarchy (XDG_DATA_HOME)."""
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base)


def python_command() -> str:
    """The interpreter a generated launcher should call.

    ``sys.executable`` is the one currently running, which is the one that is known to work. On
    Windows the windowless twin is preferred so a shortcut opens no console. An empty
    ``sys.executable`` -- possible in a frozen or embedded interpreter -- falls back to the name
    the platform resolves through PATH.
    """
    executable = sys.executable
    if not executable:
        return "python" if IS_WINDOWS else "python3"
    path = Path(executable)
    if IS_WINDOWS:
        windowless = path.with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return str(path)
