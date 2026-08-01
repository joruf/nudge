"""Start Nudge when the user logs in.

Both implementations stay inside the user's own profile, so neither needs
administrator rights -- which matters on a locked-down machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME
from .paths import IS_LINUX, IS_WINDOWS

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Nudge"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _launch_command() -> str:
    """Quoted command line that starts the app without a console window."""
    executable = Path(sys.executable)
    if IS_WINDOWS:
        windowless = executable.with_name("pythonw.exe")
        if windowless.exists():
            executable = windowless
    return f'"{executable}" -m nudge'


def _desktop_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart" / "nudge.desktop"


# ------------------------------------------------------------------ Linux


def _linux_enabled() -> bool:
    return _desktop_file().exists()


def _linux_set(enabled: bool) -> None:
    path = _desktop_file()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    root = _project_root()
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Haelt die Sitzung wach\n"
        f'Exec=sh -c \'cd "{root}" && {_launch_command()}\'\n'
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- Windows


def _windows_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _windows_set(enabled: bool) -> None:
    import winreg

    if enabled:
        root = _project_root()
        command = f'cmd /c start "" /d "{root}" {_launch_command()}'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        except OSError:
            pass


# ----------------------------------------------------------------- public


def supported() -> bool:
    return IS_LINUX or IS_WINDOWS


def is_enabled() -> bool:
    try:
        if IS_WINDOWS:
            return _windows_enabled()
        if IS_LINUX:
            return _linux_enabled()
    except Exception:
        return False
    return False


def set_enabled(enabled: bool) -> tuple[bool, str, dict]:
    """Returns (success, translation key, format params) for the caller to render."""
    try:
        if IS_WINDOWS:
            _windows_set(enabled)
        elif IS_LINUX:
            _linux_set(enabled)
        else:
            return False, "log.autostart_unsupported", {}
    except Exception as exc:
        return False, "log.autostart_failed", {"error": exc}
    key = "log.autostart_added" if enabled else "log.autostart_removed"
    return True, key, {}
