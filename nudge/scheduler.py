"""Background worker that fires each enabled technique on its own interval.

Every call into a technique happens on this single thread. That is not just
tidiness: Windows' SetThreadExecutionState is scoped to the calling thread, so
engaging and releasing it from anywhere else would silently do nothing.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .config import Config
from .eventlog import EventLog
from .i18n import Msg
from .techniques import SUSTAINED, Technique, TechniqueError

TICK = 0.25
# After this many failures in a row a technique switches itself off instead of
# filling the log with the same error forever.
MAX_CONSECUTIVE_ERRORS = 5


def _source(state: "_State") -> Msg:
    """Log label for a technique, deferred so it follows the language."""
    return Msg(f"tech.{state.technique.id}.name")


@dataclass
class Snapshot:
    """Immutable view of one technique's runtime state, for the UI thread."""

    id: str
    enabled: bool
    interval: int
    available: bool
    last_fired: float | None
    last_status: Msg | str
    error: Msg | str | None
    seconds_until_next: float | None


class _State:
    def __init__(self, technique: Technique, config: Config) -> None:
        self.technique = technique
        self.enabled = config.is_enabled(technique.id, technique.default_enabled)
        self.interval = config.interval(technique.id, technique.default_interval)
        self.next_due = 0.0
        self.last_fired: float | None = None
        self.last_status = ""
        self.error: str | None = None
        self.consecutive_errors = 0
        self.engaged = False


class Scheduler:
    def __init__(self, techniques: list[Technique], config: Config, log: EventLog) -> None:
        self._config = config
        self._log = log
        self._lock = threading.RLock()
        self._states: dict[str, _State] = {
            t.id: _State(t, config) for t in techniques
        }
        self._order = [t.id for t in techniques]
        self._commands: "queue.Queue[tuple]" = queue.Queue()
        self._master = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="nudge-scheduler", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._commands.put(("shutdown",))
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    # -------------------------------------------------------------- commands

    def set_master(self, active: bool) -> None:
        self._commands.put(("master", bool(active)))

    def set_enabled(self, tech_id: str, enabled: bool) -> None:
        self._commands.put(("enabled", tech_id, bool(enabled)))

    def set_interval(self, tech_id: str, seconds: int) -> None:
        self._commands.put(("interval", tech_id, int(seconds)))

    def fire_now(self, tech_id: str) -> None:
        self._commands.put(("fire", tech_id))

    # ----------------------------------------------------------------- state

    @property
    def master_active(self) -> bool:
        with self._lock:
            return self._master

    def snapshots(self) -> dict[str, Snapshot]:
        now = time.monotonic()
        with self._lock:
            result = {}
            for tech_id in self._order:
                state = self._states[tech_id]
                running = self._master and state.enabled
                result[tech_id] = Snapshot(
                    id=tech_id,
                    enabled=state.enabled,
                    interval=state.interval,
                    available=state.technique.availability().ok,
                    last_fired=state.last_fired,
                    last_status=state.last_status,
                    error=state.error,
                    seconds_until_next=max(0.0, state.next_due - now) if running else None,
                )
            return result

    def active_count(self) -> int:
        with self._lock:
            if not self._master:
                return 0
            return sum(
                1
                for s in self._states.values()
                if s.enabled and s.technique.availability().ok
            )

    # ------------------------------------------------------------- internals

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_commands()
            if self._stop.is_set():
                break
            self._fire_due()
            time.sleep(TICK)
        self._release_all()

    def _drain_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle(command)
            except Exception as exc:
                self._log.error(
                    Msg("log.source_app"),
                    Msg("log.command_failed", command=command[0], error=exc),
                )

    def _handle(self, command: tuple) -> None:
        name = command[0]
        if name == "shutdown":
            self._stop.set()
            return
        if name == "master":
            self._set_master(command[1])
            return
        if name == "enabled":
            self._set_enabled(command[1], command[2])
            return
        if name == "interval":
            self._set_interval(command[1], command[2])
            return
        if name == "fire":
            state = self._states.get(command[1])
            if state is not None:
                self._fire(state, manual=True)

    def _set_master(self, active: bool) -> None:
        with self._lock:
            if self._master == active:
                return
            self._master = active
        self._config.set("master_active", active)
        if active:
            self._log.info(Msg("log.source_app"), Msg("log.started"))
            for state in self._states.values():
                if state.enabled:
                    self._activate(state)
        else:
            self._release_all()
            self._log.info(Msg("log.source_app"), Msg("log.stopped"))

    def _set_enabled(self, tech_id: str, enabled: bool) -> None:
        state = self._states.get(tech_id)
        if state is None:
            return
        with self._lock:
            state.enabled = enabled
            master = self._master
        self._config.set_enabled(tech_id, enabled)
        self._config.save()
        if not master:
            return
        if enabled:
            self._activate(state)
        else:
            self._deactivate(state)

    def _set_interval(self, tech_id: str, seconds: int) -> None:
        state = self._states.get(tech_id)
        if state is None:
            return
        self._config.set_interval(tech_id, seconds)
        self._config.save()
        clamped = self._config.interval(tech_id, state.technique.default_interval)
        with self._lock:
            state.interval = clamped
            # Reschedule from now so a shortened interval takes effect at once.
            state.next_due = time.monotonic() + clamped

    def _activate(self, state: _State) -> None:
        source = _source(state)
        availability = state.technique.availability()
        if not availability.ok:
            with self._lock:
                state.error = availability.reason_msg or availability.reason
            self._log.warn(source, Msg("log.not_available", reason=availability.reason))
            return
        if state.technique.kind == SUSTAINED and not state.engaged:
            try:
                message = state.technique.engage()
                state.engaged = True
                with self._lock:
                    state.error = None
                    state.consecutive_errors = 0
                    state.last_status = message
                    state.last_fired = time.time()
                self._log.ok(source, message or Msg("log.activated"))
            except Exception as exc:
                self._note_error(state, exc)
                return
        else:
            # Periodic techniques fire straight away so the effect is visible
            # in the idle readout without waiting out a full interval.
            self._fire(state)
        with self._lock:
            state.next_due = time.monotonic() + state.interval

    def _deactivate(self, state: _State) -> None:
        try:
            state.technique.release()
        except Exception as exc:
            self._log.warn(_source(state), Msg("log.release_failed", error=exc))
        state.engaged = False
        with self._lock:
            state.last_status = Msg("status.halted")

    def _release_all(self) -> None:
        for state in self._states.values():
            if state.engaged or state.technique.kind == SUSTAINED:
                try:
                    state.technique.release()
                except Exception:
                    pass
                state.engaged = False

    def _fire_due(self) -> None:
        now = time.monotonic()
        with self._lock:
            if not self._master:
                return
            due = [
                s
                for s in self._states.values()
                if s.enabled and s.next_due <= now and s.technique.availability().ok
            ]
        for state in due:
            self._fire(state)
            with self._lock:
                state.next_due = time.monotonic() + state.interval

    def _fire(self, state: _State, manual: bool = False) -> None:
        try:
            message = state.technique.fire()
        except Exception as exc:
            self._note_error(state, exc)
            return
        with self._lock:
            state.last_fired = time.time()
            state.last_status = message or Msg("card.active")
            state.error = None
            state.consecutive_errors = 0
        if manual:
            self._log.ok(
                _source(state), Msg("log.manual", status=str(state.last_status))
            )

    def _note_error(self, state: _State, exc: Exception) -> None:
        # TechniqueError already carries a translatable message; anything else
        # only has whatever text the exception itself provides.
        detail = exc.message if isinstance(exc, TechniqueError) else (
            str(exc) or type(exc).__name__
        )
        with self._lock:
            state.consecutive_errors += 1
            state.error = detail
            count = state.consecutive_errors
        self._log.error(_source(state), detail)
        if count >= MAX_CONSECUTIVE_ERRORS:
            self._log.warn(
                _source(state), Msg("log.disabled_after_errors", count=count)
            )
            self._set_enabled(state.technique.id, False)
