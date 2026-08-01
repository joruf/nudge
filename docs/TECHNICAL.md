# Nudge — Technical Documentation

## Contents

- [Design constraints](#design-constraints)
- [Module map](#module-map)
- [Threading model](#threading-model)
- [The technique contract](#the-technique-contract)
- [Scheduler semantics](#scheduler-semantics)
- [Internationalisation](#internationalisation)
- [Idle measurement](#idle-measurement)
- [Linux platform notes](#linux-platform-notes)
- [Windows platform notes](#windows-platform-notes)
- [Why injected input can be ignored](#why-injected-input-can-be-ignored)
- [User interface](#user-interface)
- [Configuration and autostart](#configuration-and-autostart)
- [Extending Nudge](#extending-nudge)
- [Verification results](#verification-results)
- [Known limitations](#known-limitations)

---

## Design constraints

Three constraints shaped nearly every decision:

1. **No third-party packages.** The target environment is a locked-down
   corporate workstation where `pip install` fails on a proxy or a policy.
   Everything runs on the standard library plus tkinter. On Linux, optional
   modules (`Xlib`, `dbus`, `evdev`) improve individual techniques but each
   has a fallback or degrades to an unavailable technique with an explanation.
2. **Cross-platform from one codebase.** Platform-specific code is confined to
   two technique modules and two idle backends. Nothing else branches on the
   operating system.
3. **Falsifiable output.** A tool that claims to prevent idle locks but gives
   no feedback is untestable. The idle counter exists so a user can verify
   each technique instead of trusting it.

---

## Module map

```
nudge/
├── __init__.py               version, APP_NAME, APP_ID
├── __main__.py               CLI entry point, argument parsing
├── paths.py                  platform-appropriate config locations
├── config.py                 JSON settings, atomic writes, value clamping
├── eventlog.py               in-memory ring buffer of scheduler actions
├── i18n.py                   Translator and the deferred-message type
├── idle.py                   idle measurement, per-platform backends
├── scheduler.py              the single worker thread
├── sysinfo.py                VM detection and platform label
├── autostart.py              login entry on both platforms
├── locales/
│   ├── en.json               English, also the fallback catalogue
│   └── de.json               German
├── techniques/
│   ├── __init__.py           registry, loads only this platform's set
│   ├── base.py               Technique, Availability, TechniqueError
│   ├── linux_techniques.py   8 techniques, X11/D-Bus/systemd/uinput
│   └── windows_techniques.py 7 techniques, user32/kernel32 via ctypes
└── ui/
    ├── theme.py              colour palettes, font selection
    ├── widgets.py            canvas-drawn switch, button, spinner, scroller
    └── app.py                main window, idle meter, technique cards
```

Dependency direction is strictly downward: `ui` imports from the core, the
core never imports from `ui`. That is what makes `--headless` possible without
tkinter installed at all.

---

## Threading model

Exactly two threads:

- **The Tk main thread** owns every widget and the 500 ms refresh timer.
- **One scheduler thread** (`nudge-scheduler`, daemon) performs every call
  into a technique.

They communicate in one direction each:

- UI → scheduler through a `queue.Queue` of command tuples
  (`master`, `enabled`, `interval`, `fire`, `shutdown`)
- scheduler → UI through `Scheduler.snapshots()`, which returns immutable
  `Snapshot` objects under a lock, and through the `EventLog`

The UI never calls a technique directly, and the scheduler never touches a
widget.

### Why a single worker thread rather than one per technique

Windows' `SetThreadExecutionState` is **scoped to the calling thread**. The
requested state persists only as long as that thread lives, and clearing it
requires the same thread. Engaging it from a pool thread that later exits
would silently drop the request. A single long-lived worker makes the
lifetime of every sustained lock unambiguous.

The X11 connection benefits too: Xlib display objects are not thread-safe.
`_XConnection` still guards access with a lock, because `check()` runs on the
UI thread while `fire()` runs on the worker.

---

## The technique contract

Defined in `techniques/base.py`.

```python
class Technique:
    id: str                    # e.g. "linux.pointer" — also the i18n key prefix
    kind: str                  # PERIODIC or SUSTAINED
    default_interval: int
    default_enabled: bool
    invisible: bool            # False if it visibly moves the pointer

    def check(self) -> Availability
    def fire(self) -> Msg | str          # one tick
    def engage(self) -> Msg | str        # acquire a sustained lock
    def release(self) -> None            # drop it; safe when not engaged
```

Display text is **not** stored on the instance. `name`, `summary` and `detail`
are properties resolving `tech.<id>.name` and friends against the current
language catalogue on every read, so a language switch needs no object
rebuild.

`Availability` carries deferred messages rather than finished strings:

```python
Availability.no(Msg("avail.uinput_no_write"), Msg("hint.udev_rule"))
```

The result of `check()` is cached in `_availability`. Because the reason is a
`Msg`, that cached object still renders in the right language after a switch —
no re-probe required.

`TechniqueError` is the failure type that carries a translatable `Msg`. Any
other exception is recorded by its `str()`.

### Periodic versus sustained

| | Periodic | Sustained |
|---|---|---|
| Meaning of the interval | how often the action repeats | how often the lock is health-checked |
| `fire()` | performs the action | verifies and rebuilds the lock |
| `engage()` / `release()` | unused | acquire and drop the lock |
| UI label | *Interval* | *Refresh* |

Sustained techniques implement `fire()` as an idempotent check. The systemd
inhibitor, for example, tests whether its helper process is still alive and
respawns it if logind restarted.

---

## Scheduler semantics

The loop ticks every 250 ms: drain commands, fire anything due, sleep.

- **Timing uses `time.monotonic()`**, so a system clock change or NTP step
  cannot make a technique fire early, late, or in a burst.
- **Enabling a periodic technique fires it immediately** rather than after one
  full interval, so the effect is visible in the idle readout at once.
- **Changing an interval reschedules from now.** Shortening it takes effect
  immediately instead of waiting out the old, longer period.
- **Unavailable techniques are skipped** in the due-list, so a technique that
  became unusable at runtime cannot spin.
- **After five consecutive errors a technique disables itself**
  (`MAX_CONSECUTIVE_ERRORS`) and logs why. Without this a broken technique
  would emit one error per interval forever.
- **Shutdown releases every sustained lock.** `_release_all()` runs after the
  loop exits, and it calls `release()` on all sustained techniques regardless
  of whether they were ever engaged, because `release()` is required to be
  safe in that case.

---

## Internationalisation

`i18n.py` holds a module-level `Translator` singleton plus two helpers:
`t(key, **params)` for immediate translation and `Msg(key, **params)` for
deferred translation.

The distinction matters because messages outlive the moment they are created.
A log line written in English must read correctly after the user switches to
German. `Msg` stores the key and parameters and translates in `__str__`, so
the same object renders differently before and after a switch. `EventLog`
therefore stores `Msg` objects, and the log panel calls `str()` at draw time.

Catalogues are flat JSON files in `locales/`, keyed by dotted strings:

| Prefix | Contents |
|---|---|
| `header.` `footer.` `card.` `banner.` | interface chrome |
| `tech.<id>.name` / `.summary` / `.detail` | technique text |
| `avail.` / `hint.` | availability reasons and remedies |
| `status.` | what a technique reports after running |
| `err.` | failure messages |
| `log.` | scheduler and application events |
| `cli.` | command-line output and `--help` |
| `time.` | duration formatting |

`en.json` is loaded once as the permanent fallback. A key missing from another
catalogue silently falls back to English; a key missing everywhere renders as
the key itself, which makes an omission obvious rather than invisible. A
malformed placeholder returns the unformatted template instead of raising.

Language discovery is filesystem-driven: `available_languages()` globs
`locales/*.json` and reads each file's `_label`. Adding a language requires no
code change.

---

## Idle measurement

`idle.py` exposes `IdleMonitor`, which picks a backend at construction and
degrades to `UNKNOWN` (`-1.0`) rather than raising.

### Windows — `GetLastInputInfo`

```
idle_ms = (GetTickCount64() & 0xFFFFFFFF) - LASTINPUTINFO.dwTime
```

`dwTime` is a 32-bit tick count, so the current tick is masked into the same
32-bit window before subtracting, and a negative result has `0x100000000`
added back. `GetTickCount64` is used as the source to avoid the 49-day
wraparound of the 32-bit call.

### X11 — XScreenSaver extension

`Xlib.ext.screensaver.query_info(root).idle` returns milliseconds since the
last input event. The extension is queried once at construction so a missing
extension fails immediately rather than on every poll.

If a backend throws at runtime — the X server went away, the session ended —
the monitor drops it and attempts one rebuild on the next call.

---

## Linux platform notes

### XTEST rather than pointer warping

Relative pointer movement goes through
`xtest.fake_input(display, X.MotionNotify, detail=True, x=±1, y=0)`, where
`detail=True` selects relative rather than absolute coordinates.

`warp_pointer` would be the obvious alternative and is deliberately **not**
used: it moves the cursor without generating a user-activity event, so the
screensaver idle counter is unaffected. XTEST synthesises the event at the
same layer a driver does, which is precisely why it counts.

The key tap uses `XK_Shift_L`. A bare modifier registers as activity but
cannot insert a character into a focused text field — safer than F15, which
some applications bind as a shortcut.

### Screensaver reset without input

`display.force_screen_saver(X.ScreenSaverReset)` resets the X server's own
timer and produces no input event at all. This is the least intrusive Linux
technique, but its reach stops at X11: a desktop environment's lock screen
runs its own timer.

### D-Bus: why `Inhibit` needs python-dbus

`SimulateUserActivity` is a fire-and-forget method call, so the `gdbus`
command-line fallback works fine.

`Inhibit` does not, and the reason is easy to miss: **the inhibitor is bound
to the lifetime of the D-Bus connection.** A subprocess call opens a
connection, sends the request and exits — releasing the lock instantly. The
inhibit technique therefore requires python-dbus with a long-lived
`SessionBus`, and says so in its unavailability hint rather than pretending a
fallback exists.

Bus names are probed in order (freedesktop, Cinnamon, GNOME, MATE, KDE, XFCE)
and the first one that answers is cached. On failure the cache is cleared so a
restarted desktop is rediscovered.

### systemd inhibitor

Implemented as a child process:

```
systemd-inhibit --what=idle:sleep --who=Nudge --mode=block sleep infinity
```

`start_new_session=True` detaches it from Nudge's process group so a signal
to the terminal does not take the lock down. `release()` terminates it, then
kills it if it ignores the request.

### uinput

`evdev.UInput` creates a kernel-level virtual pointer. Because the events
originate below the display server, they are indistinguishable from real
hardware and work under Wayland, where XTEST is unavailable. The cost is a
permission requirement on `/dev/uinput`; `check()` reports the exact udev rule
that grants it.

---

## Windows platform notes

All Win32 access is `ctypes`, built lazily in `_Win32` so the module stays
importable on Linux — useful for editing and for the translation-key audit.

### Structure definitions

`dwExtraInfo` is `ULONG_PTR`, which is pointer-sized. It is selected at
runtime:

```python
pointer_sized = c_ulonglong if sizeof(c_void_p) == 8 else c_ulong
```

Getting this wrong misaligns `INPUT` on 64-bit and makes `SendInput` fail with
no obvious cause. `argtypes` and `restype` are set on every imported function
so ctypes does not guess at marshalling.

`SendInput` returns the number of events inserted; anything less than
requested raises a `TechniqueError` carrying `GetLastError()`.

### Techniques and their intent

| Technique | Call | Note |
|---|---|---|
| Power request | `SetThreadExecutionState(ES_CONTINUOUS \| ES_SYSTEM_REQUIRED \| ES_DISPLAY_REQUIRED)` | thread-scoped, hence the single worker thread |
| Pointer impulse | `SendInput` with `MOUSEEVENTF_MOVE` ±1 | the classic approach |
| Zero-distance move | `SendInput` with dx=dy=0 | counts as input, moves nothing |
| Key tap F15 / Shift | `SendInput` keyboard events | F15 exists on no modern keyboard |
| Double Scroll Lock | two `VK_SCROLL` taps | net state unchanged |
| Set pointer position | `SetCursorPos` | comparison technique, see below |

*Set pointer position* is included precisely because it usually **fails** to
update `GetLastInputInfo`. Running it alongside the pointer impulse tells the
user which mechanism their environment actually observes. Its description says
so explicitly rather than overselling it.

The power request is documented as ineffective against a policy-enforced lock:
the *machine inactivity limit* evaluates input idle time, not power requests.

---

## Why injected input can be ignored

Worth stating plainly, because it determines whether the whole category of
tool can work at all.

Windows has two separate input paths:

1. **The normal input queue.** `SendInput` writes here, and this is what
   `GetLastInputInfo` reflects.
2. **The Raw Input API.** Delivers data directly from the HID device.
   **Injected events never appear on this path.**

A monitoring agent that measures idleness through Raw Input is therefore
immune to every software jiggler in existence. Separately, Windows marks
synthetic events with `LLKHF_INJECTED` / `LLMHF_INJECTED`, which low-level
hooks can filter deliberately.

This is why the idle counter is a first-class feature rather than a nicety.
When the counter resets reliably and the machine locks anyway, the user has
learned something specific and actionable: the enforcement is not reading that
counter, and no user-space program will change that.

---

## User interface

### Why widgets are drawn by hand

Native Tk widgets look substantially different across Windows and the various
Linux themes, and `ttk` styling does not close the gap. Every element with a
visual identity is therefore drawn on a `Canvas`.

Pill shapes are built from **two ovals plus a bridging rectangle** rather than
a smoothed polygon; that keeps edges crisp at any size, where
`create_polygon(smooth=True)` produces visible approximation artefacts.

- `Switch` — animated toggle, easing at 35 % of remaining distance per 12 ms
  frame
- `PillButton` — hover, pressed and disabled states; auto-sizing buttons
  re-measure when their label changes, which matters when a language switch
  turns *Autostart: off* into *Autostart: aus*
- `IntervalSpinner` — steps through a ladder of sensible values and also
  accepts typed input, clamped on commit
- `ScrollFrame` — canvas viewport with a self-drawn scrollbar, handling both
  `<MouseWheel>` (Windows) and `<Button-4/5>` (X11)

Cards use a 1 px `highlightthickness` border rather than rounded corners,
since a Tk `Frame` cannot be rounded and putting interactive widgets inside a
canvas-drawn card is not worth the complexity.

Text symbols are avoided in the chrome: `☀` and `✓` render as replacement
boxes in several default UI fonts, so the theme and autostart buttons use
words.

### Refresh strategy

One `after(500)` loop updates the idle meter, all card states and the summary.
Widgets are created once and updated in place; nothing is rebuilt per tick.
The log panel is guarded by a revision counter on `EventLog`, so an unchanged
log costs one integer comparison rather than a full redraw.

### Language switching rebuilds the window

`_rebuild()` destroys every child of the root and re-runs `_build()`. Threading
a language update through every widget would mean an `apply_language()` on
each one, duplicating what construction already does. The scheduler keeps
running untouched during the rebuild, so no state is lost — only the window is
transient.

---

## Configuration and autostart

### Config file

`~/.config/nudge/config.json` on Linux, `%APPDATA%\Nudge\config.json` on
Windows.

```json
{
  "theme": "dark",
  "language": "en",
  "master_active": true,
  "lock_threshold": 300,
  "log_expanded": false,
  "geometry": "600x780+120+80",
  "techniques": {
    "linux.pointer": { "enabled": true, "interval": 60 }
  }
}
```

Writes go to a temporary file and are then `replace()`d into position, so an
interrupted save cannot leave a truncated file. Intervals are clamped to
5–3600 seconds on both read and write, which means a hand-edited absurd value
is corrected rather than honoured. A file that fails to parse is ignored and
defaults apply — a corrupt config never prevents startup.

### Autostart

- **Linux:** an XDG desktop entry at `~/.config/autostart/nudge.desktop`
- **Windows:** a `REG_SZ` value under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, written with the
  standard-library `winreg` module

Both are per-user and need no elevation. The launch command is derived from
`sys.executable` and `__file__` at write time, and prefers `pythonw.exe` on
Windows so no console appears.

---

## Extending Nudge

### Adding a technique

1. Subclass `Technique` in the appropriate platform module. Choose an id of
   the form `<platform>.<short_name>`.
2. Implement `check()` returning `Availability.yes(...)` or
   `Availability.no(reason, hint)` with `Msg` objects. Be specific: the hint
   should be a command the user can paste.
3. Implement `fire()` for a periodic technique, or `engage()`/`release()` plus
   an idempotent `fire()` for a sustained one. Return a `Msg`. Raise
   `TechniqueError(Msg(...))` on failure.
4. Add the class to that module's `build()` list.
5. Add `tech.<id>.name`, `.summary` and `.detail` to **every** catalogue in
   `locales/`.

The detail text is where honesty belongs. If a technique has a known limit —
as `xdg-screensaver reset` does — say so there rather than letting the user
discover it.

### Adding a language

Copy `locales/en.json`, name it after the language code (`fr.json`), set
`_label` to the display name, translate the values. Nudge finds it at startup
and the switcher includes it. Partial translations are fine; missing keys fall
back to English.

### Auditing translations

```bash
python3 - <<'PY'
import json, pathlib, re
base = pathlib.Path('nudge/locales')
en = json.loads((base/'en.json').read_text(encoding='utf-8'))
for path in base.glob('*.json'):
    other = json.loads(path.read_text(encoding='utf-8'))
    missing = sorted(set(en) - set(other))
    print(path.name, 'missing:', missing or 'none')
keys = set()
for p in pathlib.Path('nudge').rglob('*.py'):
    keys |= set(re.findall(r'(?:\bt|Msg)\(\s*["\']([a-z][a-z0-9_.]+)["\']', p.read_text(encoding='utf-8')))
print('referenced but undefined:', sorted(k for k in keys if k not in en) or 'none')
PY
```

---

## Verification results

Measured on Linux Mint (Cinnamon, X11) inside a VMware guest, by reading the
XScreenSaver idle counter immediately before and after firing each technique,
gated on the counter first exceeding 5 seconds:

| Technique | Before | After | Result |
|---|---|---|---|
| Pointer impulse (XTEST) | 5.2 s | 0.4 s | resets |
| Key tap Shift (XTEST) | 6.2 s | 0.4 s | resets |
| Reset X11 screensaver | 4.4 s | 0.4 s | resets |
| D-Bus SimulateUserActivity | 2.6 s | 0.4 s | resets |
| xdg-screensaver reset | 6.0 s | 6.5 s | **no effect on the X11 counter** |

Both sustained techniques were exercised through `engage()` → `fire()` →
`release()`. The systemd inhibitor held and released cleanly; the D-Bus
inhibitor obtained a cookie from `org.freedesktop.ScreenSaver` and released
it.

The `xdg-screensaver` result is reflected in that technique's own description
rather than hidden.

---

## Known limitations

- **Guest techniques cannot reach a host.** Architectural, not a bug. See the
  README.
- **Windows techniques are untested on real hardware.** The code path was
  exercised on Linux only as far as import, instantiation and translation
  resolution; the actual `SendInput` behaviour has not been observed by the
  author. The API usage follows the documented contracts.
- **No system tray icon.** That would require `pystray`, breaking the
  zero-dependency rule. Closing the window exits the application.
- **uinput needs a udev rule**, which needs root once.
- **macOS is unimplemented.** `paths.py` recognises it, but there is no
  technique set; `IOPMAssertion` would be the natural equivalent of the
  Windows power request.
- **Language switching rebuilds the window**, which collapses any expanded
  technique detail and resets the scroll position.
