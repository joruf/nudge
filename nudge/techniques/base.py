"""The contract every keep-awake technique implements."""

from __future__ import annotations

import shutil
import subprocess

from ..i18n import Msg, t

PERIODIC = "periodic"
SUSTAINED = "sustained"


class Availability:
    """Whether a technique can run here, and if not, what would fix it.

    Reason and hint are stored as deferred messages rather than finished
    strings, so a cached availability still renders correctly after the user
    switches language.
    """

    __slots__ = ("ok", "reason_msg", "hint_msg")

    def __init__(self, ok: bool, reason_msg: Msg | None = None,
                 hint_msg: Msg | None = None) -> None:
        self.ok = ok
        self.reason_msg = reason_msg
        self.hint_msg = hint_msg

    @property
    def reason(self) -> str:
        return str(self.reason_msg) if self.reason_msg is not None else ""

    @property
    def hint(self) -> str:
        return str(self.hint_msg) if self.hint_msg is not None else ""

    @staticmethod
    def yes(reason: Msg | None = None) -> "Availability":
        return Availability(True, reason)

    @staticmethod
    def no(reason: Msg, hint: Msg | None = None) -> "Availability":
        return Availability(False, reason, hint)


class Technique:
    """One switchable way of telling the system that somebody is still here.

    Subclasses override :meth:`check` plus either :meth:`fire` (``PERIODIC``,
    an action repeated on an interval) or :meth:`engage`/:meth:`release`
    (``SUSTAINED``, a lock held for as long as the technique is on). Sustained
    techniques may also implement :meth:`fire` to re-assert their lock, which
    is what the interval means for them.

    Display text is not stored on the instance: name, summary and detail are
    looked up from the language files under ``tech.<id>.*`` every time they
    are read.
    """

    def __init__(self, id: str, kind: str = PERIODIC, default_interval: int = 60,
                 default_enabled: bool = False, invisible: bool = True) -> None:
        self.id = id
        self.kind = kind
        self.default_interval = default_interval
        self.default_enabled = default_enabled
        # False for techniques that move the pointer or press keys, so the UI
        # can warn that they are observable while the machine is in use.
        self.invisible = invisible
        self._availability: Availability | None = None

    # ------------------------------------------------------------- display

    @property
    def name(self) -> str:
        return t(f"tech.{self.id}.name")

    @property
    def summary(self) -> str:
        return t(f"tech.{self.id}.summary")

    @property
    def detail(self) -> str:
        return t(f"tech.{self.id}.detail")

    @property
    def interval_label(self) -> str:
        return t("card.interval") if self.kind == PERIODIC else t("card.refresh")

    # ---------------------------------------------------------- lifecycle

    def check(self) -> Availability:
        return Availability.yes()

    def availability(self, refresh: bool = False) -> Availability:
        if self._availability is None or refresh:
            try:
                self._availability = self.check()
            except Exception as exc:  # a probe must never crash the app
                self._availability = Availability.no(
                    Msg("avail.probe_failed", error=exc)
                )
        return self._availability

    def fire(self) -> Msg | str:
        """Perform one tick. Returns a short status shown in the log."""
        return ""

    def engage(self) -> Msg | str:
        """Acquire a sustained lock. Returns a short status."""
        return ""

    def release(self) -> None:
        """Drop the sustained lock. Must be safe to call when not engaged."""


class TechniqueError(Exception):
    """Failure that already carries a translatable message."""

    def __init__(self, message: Msg) -> None:
        super().__init__(str(message))
        self.message = message

    def __str__(self) -> str:
        return str(self.message)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    """Run a helper binary without ever opening a console window on Windows."""
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)
