"""Keep-awake techniques for Windows.

All of these talk to user32/kernel32 through ctypes, so there is no dependency
beyond the standard library. The Win32 structures are built lazily, which keeps
this module importable (and testable) on other platforms.
"""

from __future__ import annotations

import ctypes
import threading

from ..i18n import Msg
from .base import PERIODIC, SUSTAINED, Availability, Technique, TechniqueError

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK_SHIFT = 0x10
VK_SCROLL = 0x91
VK_F15 = 0x7E

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040


class _Win32:
    """Lazily built ctypes bindings for the handful of calls we need."""

    _instance: "_Win32 | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        from ctypes import wintypes

        pointer_sized = (
            ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
        )

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", pointer_sized),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", pointer_sized),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class _InputUnion(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]

        self.MOUSEINPUT = MOUSEINPUT
        self.KEYBDINPUT = KEYBDINPUT
        self.INPUT = INPUT

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self.user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )
        self.user32.SendInput.restype = wintypes.UINT

        self.user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        self.user32.SetCursorPos.restype = wintypes.BOOL

        self.user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
        self.user32.GetCursorPos.restype = wintypes.BOOL

        self.kernel32.SetThreadExecutionState.argtypes = (ctypes.c_uint32,)
        self.kernel32.SetThreadExecutionState.restype = ctypes.c_uint32

        self.POINT = wintypes.POINT

    @classmethod
    def get(cls) -> "_Win32":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------ senders

    def send(self, *inputs) -> None:
        array_type = self.INPUT * len(inputs)
        array = array_type(*inputs)
        sent = self.user32.SendInput(len(inputs), array, ctypes.sizeof(self.INPUT))
        if sent != len(inputs):
            raise TechniqueError(
                Msg("err.sendinput", sent=sent, total=len(inputs),
                    code=ctypes.get_last_error())
            )

    def mouse_input(self, dx: int, dy: int):
        event = self.INPUT(type=INPUT_MOUSE)
        event.mi = self.MOUSEINPUT(
            dx=dx, dy=dy, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0
        )
        return event

    def key_input(self, vk: int, up: bool):
        event = self.INPUT(type=INPUT_KEYBOARD)
        event.ki = self.KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=KEYEVENTF_KEYUP if up else 0,
            time=0,
            dwExtraInfo=0,
        )
        return event


def _win_available() -> Availability:
    try:
        _Win32.get()
    except Exception as exc:
        return Availability.no(Msg("avail.win32_unreachable", error=exc))
    return Availability.yes()


# --------------------------------------------------------------------------
# Techniques
# --------------------------------------------------------------------------


class ExecutionState(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.execstate",
            kind=SUSTAINED,
            default_interval=240,
            default_enabled=True,
        )
        self._engaged = False

    def check(self) -> Availability:
        return _win_available()

    def _assert_state(self) -> None:
        api = _Win32.get()
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        if api.kernel32.SetThreadExecutionState(flags) == 0:
            raise TechniqueError(Msg("err.execstate_denied"))

    def engage(self) -> Msg:
        self._assert_state()
        self._engaged = True
        return Msg("status.execstate_set")

    def fire(self) -> Msg:
        # The flag is per thread; re-assert so it survives any scheduler restart.
        self._assert_state()
        return Msg("status.execstate_refreshed")

    def release(self) -> None:
        if not self._engaged:
            return
        try:
            _Win32.get().kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass
        self._engaged = False


class MouseImpulse(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.mouse_impulse",
            kind=PERIODIC,
            default_interval=60,
            default_enabled=True,
            invisible=False,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        api.send(api.mouse_input(1, 0))
        api.send(api.mouse_input(-1, 0))
        return Msg("status.pointer_moved")


class MouseZeroMove(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.mouse_zero",
            kind=PERIODIC,
            default_interval=60,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        api.send(api.mouse_input(0, 0))
        return Msg("status.zero_move")


class KeyTapF15(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.key_f15",
            kind=PERIODIC,
            default_interval=120,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        api.send(api.key_input(VK_F15, False), api.key_input(VK_F15, True))
        return Msg("status.f15_tapped")


class KeyTapShift(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.key_shift",
            kind=PERIODIC,
            default_interval=120,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        api.send(api.key_input(VK_SHIFT, False), api.key_input(VK_SHIFT, True))
        return Msg("status.shift_tapped")


class ScrollLockToggle(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.scroll_lock",
            kind=PERIODIC,
            default_interval=120,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        for _ in range(2):
            api.send(api.key_input(VK_SCROLL, False), api.key_input(VK_SCROLL, True))
        return Msg("status.scroll_toggled")


class CursorReposition(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="windows.setcursorpos",
            kind=PERIODIC,
            default_interval=60,
            invisible=False,
        )

    def check(self) -> Availability:
        return _win_available()

    def fire(self) -> Msg:
        api = _Win32.get()
        point = api.POINT()
        if not api.user32.GetCursorPos(ctypes.byref(point)):
            raise TechniqueError(Msg("err.getcursorpos"))
        api.user32.SetCursorPos(point.x + 1, point.y)
        api.user32.SetCursorPos(point.x, point.y)
        return Msg("status.cursor_nudged", x=point.x, y=point.y)


def build() -> list[Technique]:
    return [
        ExecutionState(),
        MouseImpulse(),
        MouseZeroMove(),
        KeyTapF15(),
        KeyTapShift(),
        ScrollLockToggle(),
        CursorReposition(),
    ]
