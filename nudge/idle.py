"""How long the session has been without user input.

This is the feedback loop that makes the rest of the app verifiable: if a
technique really resets the system's idle timer, this number drops back to
zero every time it fires. If it keeps climbing, the technique is being
ignored -- which is exactly what happens when an endpoint agent filters
injected input.
"""

from __future__ import annotations

import ctypes
import os

from .i18n import t
from .paths import platform_key

UNKNOWN = -1.0


class _WindowsIdle:
    def __init__(self) -> None:
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._struct = LASTINPUTINFO
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.GetLastInputInfo.argtypes = (ctypes.POINTER(LASTINPUTINFO),)
        self._user32.GetLastInputInfo.restype = wintypes.BOOL
        # GetTickCount64 avoids the 49-day wraparound of the 32-bit variant.
        self._kernel32.GetTickCount64.restype = ctypes.c_uint64

    def seconds(self) -> float:
        info = self._struct()
        info.cbSize = ctypes.sizeof(self._struct)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            return UNKNOWN
        now = self._kernel32.GetTickCount64()
        # dwTime is a 32-bit tick count; compare within the same 32-bit window.
        elapsed_ms = (now & 0xFFFFFFFF) - info.dwTime
        if elapsed_ms < 0:
            elapsed_ms += 0x100000000
        return elapsed_ms / 1000.0


class _X11Idle:
    def __init__(self) -> None:
        from Xlib import display
        from Xlib.ext import screensaver

        self._display = display.Display()
        self._root = self._display.screen().root
        self._screensaver = screensaver
        # Fail fast at construction if the extension is missing.
        self._screensaver.query_info(self._root)

    def seconds(self) -> float:
        return self._screensaver.query_info(self._root).idle / 1000.0


class IdleMonitor:
    """Best-effort idle reader, degrading to UNKNOWN rather than raising."""

    def __init__(self) -> None:
        self._backend = None
        self._name = ""
        self._init_backend()

    def _init_backend(self) -> None:
        platform = platform_key()
        if platform == "windows":
            try:
                self._backend = _WindowsIdle()
                self._name = "GetLastInputInfo"
                return
            except Exception:
                pass
        else:
            if os.environ.get("DISPLAY"):
                try:
                    self._backend = _X11Idle()
                    self._name = "XScreenSaver"
                    return
                except Exception:
                    pass
        self._backend = None

    @property
    def backend_name(self) -> str:
        # API names stay untranslated; only the "none" case is a phrase.
        return self._name or t("header.backend_none")

    @property
    def available(self) -> bool:
        return self._backend is not None

    def seconds(self) -> float:
        if self._backend is None:
            return UNKNOWN
        try:
            return self._backend.seconds()
        except Exception:
            # The X server or session went away; try once to rebuild.
            self._backend = None
            self._init_backend()
            return UNKNOWN


def format_idle(seconds: float) -> str:
    if seconds < 0:
        return t("time.unknown")
    if seconds < 60:
        return t("time.seconds", value=int(seconds))
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return t("time.minutes", minutes=minutes, seconds=f"{secs:02d}")
    hours, minutes = divmod(minutes, 60)
    return t("time.hours", hours=hours, minutes=f"{minutes:02d}")
