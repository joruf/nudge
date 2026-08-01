"""Keep-awake techniques for Linux / X11 / Wayland desktops.

Every technique here acts inside the local session only. Running in a virtual
machine, that means the guest -- synthetic input generated here never reaches
the host's input queue, so it cannot hold a host session open. See the VM
banner in the UI.
"""

from __future__ import annotations

import os
import subprocess
import threading

from ..i18n import Msg
from .base import (
    PERIODIC,
    SUSTAINED,
    Availability,
    Technique,
    TechniqueError,
    have,
    run,
)

# Desktops disagree on which bus name owns the screensaver, so we try the
# common ones in order and remember whichever answered.
SCREENSAVER_BUSES = [
    ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"),
    ("org.cinnamon.ScreenSaver", "/org/cinnamon/ScreenSaver"),
    ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver"),
    ("org.mate.ScreenSaver", "/org/mate/ScreenSaver"),
    ("org.kde.screensaver", "/ScreenSaver"),
    ("org.xfce.ScreenSaver", "/org/xfce/ScreenSaver"),
]


def session_type() -> str:
    return (os.environ.get("XDG_SESSION_TYPE") or "").lower()


def has_x_display() -> bool:
    return bool(os.environ.get("DISPLAY"))


def service_label(bus_name: str) -> str:
    parts = bus_name.split(".")
    return parts[1] if len(parts) > 1 else bus_name


# --------------------------------------------------------------------------
# Shared X11 connection. Xlib display objects are not thread-safe, so every
# use goes through one lock.
# --------------------------------------------------------------------------


class _XConnection:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._display = None
        self._failed = False

    def available(self) -> bool:
        if not has_x_display():
            return False
        try:
            import Xlib  # noqa: F401
        except ImportError:
            return False
        return True

    def _connect(self):
        if self._display is None and not self._failed:
            try:
                from Xlib import display

                self._display = display.Display()
            except Exception:
                self._failed = True
                self._display = None
        return self._display

    def use(self):
        """Context manager yielding a connected display, or None."""
        conn = self

        class _Ctx:
            def __enter__(self):
                conn._lock.acquire()
                return conn._connect()

            def __exit__(self, exc_type, exc, tb):
                # A broken pipe means the X server went away; drop the handle
                # so the next call reconnects instead of failing forever.
                if exc_type is not None:
                    conn._display = None
                    conn._failed = False
                conn._lock.release()
                return False

        return _Ctx()


XCONN = _XConnection()


# --------------------------------------------------------------------------
# Shared D-Bus session connection. It must be long-lived: screensaver
# inhibitors are released automatically when the owning connection closes.
# --------------------------------------------------------------------------


class _DBusConnection:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bus = None
        self._failed = False

    def available(self) -> bool:
        try:
            import dbus  # noqa: F401
        except ImportError:
            return False
        return bool(
            os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or os.path.exists(f"/run/user/{os.getuid()}/bus")
        )

    def bus(self):
        with self._lock:
            if self._bus is None and not self._failed:
                try:
                    import dbus

                    self._bus = dbus.SessionBus()
                except Exception:
                    self._failed = True
            return self._bus

    def interface(self, bus_name: str, path: str, iface: str):
        import dbus

        bus = self.bus()
        if bus is None:
            return None
        return dbus.Interface(bus.get_object(bus_name, path), iface)


DBUS = _DBusConnection()


def gdbus_call(bus_name: str, path: str, method: str) -> bool:
    """Fallback for desktops where python-dbus is missing."""
    if not have("gdbus"):
        return False
    result = run(
        [
            "gdbus", "call", "--session",
            "--dest", bus_name,
            "--object-path", path,
            "--method", method,
        ]
    )
    return result.returncode == 0


# --------------------------------------------------------------------------
# Techniques
# --------------------------------------------------------------------------


class PointerImpulse(Technique):
    """Nudge the pointer one pixel and immediately back."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.pointer",
            kind=PERIODIC,
            default_interval=60,
            default_enabled=True,
            invisible=False,
        )

    def check(self) -> Availability:
        if XCONN.available():
            return Availability.yes(Msg("avail.xtest_xlib"))
        if have("xdotool") and has_x_display():
            return Availability.yes(Msg("avail.xdotool_fallback"))
        if session_type() == "wayland":
            return Availability.no(
                Msg("avail.wayland_no_xtest"), Msg("hint.use_uinput")
            )
        return Availability.no(Msg("avail.no_x11"), Msg("hint.install_xlib"))

    def fire(self) -> Msg:
        if XCONN.available():
            from Xlib import X
            from Xlib.ext import xtest

            with XCONN.use() as display:
                if display is not None:
                    xtest.fake_input(display, X.MotionNotify, detail=True, x=1, y=0)
                    xtest.fake_input(display, X.MotionNotify, detail=True, x=-1, y=0)
                    display.sync()
                    return Msg("status.pointer_moved")
        if have("xdotool"):
            run(["xdotool", "mousemove_relative", "--", "1", "0"])
            run(["xdotool", "mousemove_relative", "--", "-1", "0"])
            return Msg("status.pointer_moved_xdotool")
        raise TechniqueError(Msg("err.no_input_method"))


class KeyTap(Technique):
    """Press and release a modifier that produces no character."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.keytap",
            kind=PERIODIC,
            default_interval=120,
            invisible=False,
        )

    def check(self) -> Availability:
        if XCONN.available():
            return Availability.yes(Msg("avail.xtest_xlib"))
        if have("xdotool") and has_x_display():
            return Availability.yes(Msg("avail.xdotool_fallback"))
        return Availability.no(Msg("avail.no_x11"), Msg("hint.install_xlib"))

    def fire(self) -> Msg:
        if XCONN.available():
            from Xlib import X, XK
            from Xlib.ext import xtest

            with XCONN.use() as display:
                if display is not None:
                    keycode = display.keysym_to_keycode(XK.XK_Shift_L)
                    xtest.fake_input(display, X.KeyPress, keycode)
                    xtest.fake_input(display, X.KeyRelease, keycode)
                    display.sync()
                    return Msg("status.shift_tapped")
        if have("xdotool"):
            run(["xdotool", "key", "shift"])
            return Msg("status.shift_tapped_xdotool")
        raise TechniqueError(Msg("err.no_input_method"))


class ScreenSaverReset(Technique):
    """Ask the X server directly to reset its screensaver timer."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.xreset",
            kind=PERIODIC,
            default_interval=60,
            default_enabled=True,
        )

    def check(self) -> Availability:
        if XCONN.available():
            return Availability.yes(Msg("avail.xlib_force"))
        if have("xset") and has_x_display():
            return Availability.yes(Msg("avail.xset_fallback"))
        return Availability.no(Msg("avail.no_x11"), Msg("hint.install_xlib"))

    def fire(self) -> Msg:
        if XCONN.available():
            from Xlib import X

            with XCONN.use() as display:
                if display is not None:
                    display.force_screen_saver(X.ScreenSaverReset)
                    display.sync()
                    return Msg("status.screensaver_reset")
        if have("xset"):
            run(["xset", "s", "reset"])
            run(["xset", "dpms", "force", "on"])
            return Msg("status.xset_reset")
        raise TechniqueError(Msg("err.no_x11"))


class SimulateUserActivity(Technique):
    """Tell the desktop's screensaver service that the user is active."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.dbus_activity",
            kind=PERIODIC,
            default_interval=60,
            default_enabled=True,
        )
        self._resolved: tuple[str, str] | None = None

    def check(self) -> Availability:
        if DBUS.available():
            return Availability.yes(Msg("avail.dbus_session"))
        if have("gdbus"):
            return Availability.yes(Msg("avail.gdbus_fallback"))
        return Availability.no(Msg("avail.no_dbus"), Msg("hint.install_dbus"))

    def _targets(self) -> list[tuple[str, str]]:
        if self._resolved:
            return [self._resolved]
        return SCREENSAVER_BUSES

    def fire(self) -> Msg:
        for bus_name, path in self._targets():
            try:
                iface = DBUS.interface(bus_name, path, bus_name)
                if iface is not None:
                    iface.SimulateUserActivity()
                    self._resolved = (bus_name, path)
                    return Msg("status.activity_reported",
                               service=service_label(bus_name))
            except Exception:
                pass
            if gdbus_call(bus_name, path, f"{bus_name}.SimulateUserActivity"):
                self._resolved = (bus_name, path)
                return Msg("status.activity_reported_gdbus",
                           service=service_label(bus_name))
        # A previously working target vanished, e.g. the desktop restarted.
        self._resolved = None
        raise TechniqueError(Msg("err.no_screensaver_service"))


class XdgScreenSaverReset(Technique):
    def __init__(self) -> None:
        super().__init__(
            id="linux.xdg_reset",
            kind=PERIODIC,
            default_interval=120,
        )

    def check(self) -> Availability:
        if have("xdg-screensaver"):
            return Availability.yes()
        return Availability.no(Msg("avail.xdg_missing"), Msg("hint.install_xdgutils"))

    def fire(self) -> Msg:
        result = run(["xdg-screensaver", "reset"], timeout=10)
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:120]
            raise TechniqueError(
                Msg("err.xdg_failed", error=detail or str(Msg("err.nonzero_exit")))
            )
        return Msg("status.xdg_reset")


class SystemdInhibit(Technique):
    """Hold a logind inhibitor lock for idle and sleep."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.systemd_inhibit",
            kind=SUSTAINED,
            default_interval=300,
            default_enabled=True,
        )
        self._process: subprocess.Popen | None = None

    def check(self) -> Availability:
        if have("systemd-inhibit"):
            return Availability.yes()
        return Availability.no(Msg("avail.systemd_missing"))

    def engage(self) -> Msg:
        self.release()
        self._process = subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=idle:sleep",
                "--who=Nudge",
                "--why=User keeps the session open",
                "--mode=block",
                "sleep", "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return Msg("status.inhibit_held")

    def fire(self) -> Msg:
        # Re-acquire if the helper died, e.g. because logind restarted.
        if self._process is None or self._process.poll() is not None:
            self.engage()
            return Msg("status.rebuilt")
        return Msg("status.inhibit_active")

    def release(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class ScreenSaverInhibit(Technique):
    """Hold a freedesktop screensaver inhibitor cookie."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.dbus_inhibit",
            kind=SUSTAINED,
            default_interval=300,
        )
        self._cookie: int | None = None
        self._target: tuple[str, str] | None = None

    def check(self) -> Availability:
        if DBUS.available():
            return Availability.yes()
        return Availability.no(
            Msg("avail.no_python_dbus"), Msg("hint.needs_persistent_dbus")
        )

    def engage(self) -> Msg:
        self.release()
        for bus_name, path in SCREENSAVER_BUSES:
            try:
                iface = DBUS.interface(bus_name, path, bus_name)
                if iface is None:
                    continue
                self._cookie = int(iface.Inhibit("Nudge", "Keep session open"))
                self._target = (bus_name, path)
                return Msg("status.cookie_held", service=service_label(bus_name),
                           cookie=self._cookie)
            except Exception:
                continue
        raise TechniqueError(Msg("err.no_inhibit_service"))

    def fire(self) -> Msg:
        if self._cookie is None:
            self.engage()
            return Msg("status.rebuilt")
        return Msg("status.cookie_active", cookie=self._cookie)

    def release(self) -> None:
        if self._cookie is not None and self._target is not None:
            bus_name, path = self._target
            try:
                iface = DBUS.interface(bus_name, path, bus_name)
                if iface is not None:
                    iface.UnInhibit(self._cookie)
            except Exception:
                pass
        self._cookie = None
        self._target = None


class UinputPointer(Technique):
    """Kernel-level virtual mouse. The only option that works under Wayland."""

    def __init__(self) -> None:
        super().__init__(
            id="linux.uinput",
            kind=PERIODIC,
            default_interval=60,
            invisible=False,
        )
        self._device = None
        self._lock = threading.Lock()

    def check(self) -> Availability:
        try:
            import evdev  # noqa: F401
        except ImportError:
            return Availability.no(Msg("avail.evdev_missing"), Msg("hint.install_evdev"))
        if not os.path.exists("/dev/uinput"):
            return Availability.no(
                Msg("avail.uinput_missing"), Msg("hint.modprobe_uinput")
            )
        if not os.access("/dev/uinput", os.W_OK):
            return Availability.no(Msg("avail.uinput_no_write"), Msg("hint.udev_rule"))
        return Availability.yes(Msg("avail.kernel_input"))

    def _open(self):
        if self._device is None:
            from evdev import UInput
            from evdev import ecodes as e

            self._device = UInput(
                {e.EV_REL: [e.REL_X, e.REL_Y], e.EV_KEY: [e.BTN_LEFT]},
                name="Nudge Virtual Pointer",
            )
        return self._device

    def fire(self) -> Msg:
        from evdev import ecodes as e

        with self._lock:
            device = self._open()
            device.write(e.EV_REL, e.REL_X, 1)
            device.syn()
            device.write(e.EV_REL, e.REL_X, -1)
            device.syn()
        return Msg("status.uinput_moved")

    def release(self) -> None:
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                self._device = None


def build() -> list[Technique]:
    return [
        PointerImpulse(),
        ScreenSaverReset(),
        SimulateUserActivity(),
        SystemdInhibit(),
        KeyTap(),
        ScreenSaverInhibit(),
        UinputPointer(),
        XdgScreenSaverReset(),
    ]
