"""The entry that puts Nudge in the desktop's own list of programs.

`Nudge.desktop` in the project root already starts the program by double-click: it locates itself
through the `%k` field code, so it needs no installation and no absolute path written into it. What
it does need is an icon, and an `Icon=` line can only name a theme icon or an absolute file --
never a path relative to itself. `ensure_theme_icon()` is the answer, and the interface calls it on
every start: the rendered icons go into the user's own icon theme, where `Icon=nudge` resolves for
the file manager, the panel and the menu alike.

Autostart (see autostart.py) answers "start this at login". This module answers the other half,
"put it where I look for programs", which on Linux means a copy of that same file in the
application menu and on Windows a shortcut in the Start menu. Both are per-user, and the copies get
absolute paths rather than `%k`, because from the menu directory `%k` would point at the copy
instead of at the program.

The interface offers this as a switch, so the same call has to install, remove and report the
current state. `set_installed` therefore returns what autostart returns: a success flag and a
translation key for the caller to render, because this module has no business choosing a language.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from . import APP_NAME
from .paths import (
    DESKTOP_FILENAME,
    DESKTOP_LAUNCHER,
    IS_LINUX,
    IS_WINDOWS,
    launcher_arguments,
    launcher_directory,
    data_dir,
    python_command,
)
from .ui.window_icon import ICON_BASENAME, ICON_SIZES, WM_CLASS_PUBLISHED

#: Used when no icon file could be written anywhere. A stock name from the icon theme is a better
#: answer than an empty Icon= line, which some panels draw as a broken image.
FALLBACK_ICON = "preferences-desktop-screensaver"

#: What an installed copy says when Nudge.desktop is missing -- a clone with the file deleted, or
#: an installed package that did not carry it along.
DEFAULT_TEMPLATE = (
    "[Desktop Entry]\n"
    "Version=1.0\n"
    "Type=Application\n"
    f"Name={APP_NAME}\n"
    "Comment=Keeps the workstation from going idle, with switchable techniques\n"
    f"Icon={ICON_BASENAME}\n"
    "Exec=python3 nudge.py\n"
    "Terminal=false\n"
    "Categories=Utility;\n"
    "StartupNotify=true\n"
    f"StartupWMClass={WM_CLASS_PUBLISHED}\n"
)

WINDOWS_SHORTCUT_NAME = f"{APP_NAME}.lnk"

#: Keeps a console from flashing up while the shortcut is written. subprocess only defines the flag
#: on Windows, and POSIX only objects to a non-zero one, so asking for it this way runs anywhere --
#: which is what makes the Windows branch testable from a Linux machine.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------ Linux


def _applications_dir() -> Path:
    return data_dir() / "applications"


def _entry_path() -> Path:
    return _applications_dir() / DESKTOP_FILENAME


def _theme_root() -> Path:
    return data_dir() / "icons" / "hicolor"


def _theme_icon_path(size: int) -> Path:
    return _theme_root() / f"{size}x{size}" / "apps" / f"{ICON_BASENAME}.png"


def _refresh_icon_cache() -> bool:
    """Rebuild the icon theme cache, if there is one in the way.

    Measured, not assumed: GTK trusts an existing `icon-theme.cache` over the directory it sits
    in, so an icon copied next to a stale cache is simply not there as far as the menu is
    concerned -- `Gtk.IconTheme.has_icon("nudge")` stays False with the file plainly on disk.
    Where no cache exists GTK reads the directory itself and there is nothing to do.

    Returns:
        bool: True when the icon can be reached through the theme -- because the cache was
        rebuilt, or because no cache stands in front of it.
    """
    root = _theme_root()
    if not (root / "icon-theme.cache").exists():
        return True

    tool = shutil.which("gtk-update-icon-cache") or shutil.which("gtk-update-icon-cache-3.0")
    if tool is None:
        return False
    try:
        # -t skips the index.theme check, which a user's own hicolor directory usually has not got.
        result = subprocess.run([tool, "-q", "-f", "-t", str(root)], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def ensure_theme_icon() -> str:
    """Put the icon where a desktop looks for icons, and say what to write in an Icon= line.

    Cheap to call on every start: with the files already in place it does nothing but four
    `is_file()` checks. A themed icon -- `Icon=nudge` resolved through hicolor -- is what lets each
    consumer pick the size it wants instead of scaling one file, and it is the only form of icon a
    `.desktop` file can name without knowing where it will end up. Where the theme cannot be
    written, or where its cache cannot be brought up to date afterwards, an absolute path to a
    rendered file still works and is what gets returned instead.

    Returns:
        str: The value for the Icon= line.
    """
    from .ui.window_icon import ensure_icon_files, primary_icon_file

    if all(_theme_icon_path(size).is_file() for size in ICON_SIZES):
        return ICON_BASENAME

    sources = ensure_icon_files()
    installed = 0
    for size, source in zip(ICON_SIZES, sources):
        target = _theme_icon_path(size)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            installed += 1
        except OSError:
            continue

    if installed == len(ICON_SIZES) and _refresh_icon_cache():
        return ICON_BASENAME
    fallback = primary_icon_file()
    return str(fallback) if fallback is not None else FALLBACK_ICON


def build_entry(icon: str, extra: Sequence[str] = ()) -> str:
    """The contents of the installed .desktop file.

    `Nudge.desktop` in the project root is the source of the names, categories and translations;
    only the lines that cannot be written down in advance are replaced. Exec becomes an absolute
    command, because the `%k` trick that makes the shipped file self-locating would point a copy in
    the menu directory at the menu directory. Icon needs the theme name or an absolute path, and
    StartupWMClass has to match what the running window reports or the panel treats launcher and
    window as two unrelated things. The comment lines that explain `%k` are left out of the copy,
    where they would only describe something that is no longer true of it.

    Args:
        icon: Value for the Icon= line.
        extra: Further lines to append, for a variant of the entry -- the autostart copy adds the
            key that lets GNOME switch it off without deleting the file.

    Returns:
        str: A complete desktop entry.
    """
    try:
        template = DESKTOP_LAUNCHER.read_text(encoding="utf-8")
    except OSError:
        template = DEFAULT_TEMPLATE

    replacements = {
        "Exec": "Exec=" + " ".join(f'"{part}"' for part in (python_command(), *launcher_arguments())),
        "Icon": f"Icon={icon}",
        "Path": f"Path={launcher_directory()}",
        "StartupWMClass": f"StartupWMClass={WM_CLASS_PUBLISHED}",
    }
    seen: set[str] = set()
    lines: list[str] = []
    for line in template.splitlines():
        if line.startswith("#"):
            continue
        key = line.split("=", 1)[0]
        if key in replacements:
            lines.append(replacements[key])
            seen.add(key)
        else:
            lines.append(line)
    for key, value in replacements.items():
        if key not in seen:
            lines.append(value)
    for line in extra:
        if line.split("=", 1)[0] not in seen:
            lines.append(line)

    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _refresh_menu() -> None:
    """Ask the desktop to notice the new entry, where there is a tool for it.

    Most desktops watch the directory and need no prompting; the ones that keep a cache do. Either
    way a failure here is not a failure of the installation, so it is swallowed.
    """
    tool = shutil.which("update-desktop-database")
    if tool is None:
        return
    try:
        subprocess.run([tool, str(_applications_dir())], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


def _linux_installed() -> bool:
    return _entry_path().is_file()


def _linux_set(enabled: bool) -> None:
    path = _entry_path()
    if not enabled:
        # The icon stays. It belongs to the user's icon theme rather than to this entry, and
        # Nudge.desktop in the program directory still names it.
        path.unlink(missing_ok=True)
        _refresh_menu()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_entry(ensure_theme_icon()), encoding="utf-8")
    # Executable is not required in the applications directory, but a file manager refuses to
    # launch a copy of this file from anywhere else without it.
    path.chmod(0o755)
    _refresh_menu()


# ---------------------------------------------------------------- Windows


def _start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _shortcut_path() -> Path:
    return _start_menu_dir() / WINDOWS_SHORTCUT_NAME


def _quote_powershell(value: str) -> str:
    """A PowerShell single-quoted string, in which the only escape is a doubled quote."""
    return "'" + str(value).replace("'", "''") + "'"


def _windows_installed() -> bool:
    return _shortcut_path().is_file()


def _windows_set(enabled: bool) -> None:
    """Create or delete the Start menu shortcut.

    A .lnk is a COM object, and the standard library cannot write one. PowerShell can, is present
    on every supported Windows, and needs no elevation for a shortcut inside the user's own
    profile -- which is why it is preferred over shipping a binary helper.
    """
    path = _shortcut_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return

    from .ui.window_icon import ensure_ico_file

    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_theme_icon()
    icon = ensure_ico_file()
    # The launcher path is quoted twice over: once for PowerShell, and once inside the argument
    # string itself, because that is what the shortcut hands to the interpreter later on.
    arguments = " ".join(f'"{part}"' for part in launcher_arguments())
    description = "Keeps the workstation from going idle"
    script = [
        "$shortcut = (New-Object -ComObject WScript.Shell)"
        f".CreateShortcut({_quote_powershell(path)})",
        f"$shortcut.TargetPath = {_quote_powershell(python_command())}",
        f"$shortcut.Arguments = {_quote_powershell(arguments)}",
        f"$shortcut.WorkingDirectory = {_quote_powershell(launcher_directory())}",
        f"$shortcut.Description = {_quote_powershell(description)}",
    ]
    if icon is not None:
        script.append(f"$shortcut.IconLocation = {_quote_powershell(str(icon) + ',0')}")
    script.append("$shortcut.Save()")

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise RuntimeError("PowerShell is needed to create a shortcut and was not found")

    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", "; ".join(script)],
        capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
    )
    if result.returncode != 0 or not path.is_file():
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "the shortcut was not created")


# ----------------------------------------------------------------- public


def supported() -> bool:
    """Whether this platform has a program list this module knows how to write to."""
    return IS_LINUX or IS_WINDOWS


def location() -> Path | None:
    """Where the entry is, or would be. None where the platform has no such place."""
    if IS_LINUX:
        return _entry_path()
    if IS_WINDOWS:
        return _shortcut_path()
    return None


def is_installed() -> bool:
    try:
        if IS_WINDOWS:
            return _windows_installed()
        if IS_LINUX:
            return _linux_installed()
    except Exception:
        return False
    return False


def set_installed(enabled: bool) -> tuple[bool, str, dict]:
    """Install or remove the entry.

    Returns:
        tuple[bool, str, dict]: Success, a translation key, and its parameters.
    """
    try:
        if IS_WINDOWS:
            _windows_set(enabled)
        elif IS_LINUX:
            _linux_set(enabled)
        else:
            return False, "log.entry_unsupported", {}
    except Exception as exc:
        return False, "log.entry_failed", {"error": exc}
    key = "log.entry_added" if enabled else "log.entry_removed"
    return True, key, {"path": location() or ""}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "show"
    if action == "show":
        print(f"installed: {is_installed()}  at: {location()}")
    else:
        ok, key, params = set_installed(action == "install")
        print(f"{'ok' if ok else 'failed'}: {key} {params}")
