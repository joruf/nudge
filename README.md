# Nudge

Keeps a workstation from going idle — and proves whether it is working.

Fifteen individual anti-idle techniques, each switchable on its own interval,
plus a live idle counter that shows you in real time whether a technique
actually reaches the system's idle timer. Runs on Linux and Windows.

![Nudge main window](docs/images/main-dark.png)

**No dependencies beyond Python and tkinter. No `pip` required.** That is a
deliberate design constraint: on a locked-down corporate machine, a package
download is usually the point where everything else fails.

---

## Read this first: guests and hosts are separate

If you run Nudge inside a virtual machine, every technique acts **inside that
VM only**. The host never sees it.

The reason is the direction in which input events flow:

| What happens | Path | Effect |
|---|---|---|
| You move the real mouse | The driver in the **host** creates the event, the host resets its own idle counter, then forwards the movement to the guest | Host **and** guest stay awake |
| Nudge creates a movement in the guest | XTEST or uinput creates the event **in the guest** | Only the guest stays awake |

There is no return channel from the guest into the host's input stack. To stop
a host operating system from locking, Nudge has to run **on the host**. It
detects virtualisation on its own and shows a banner saying so.

---

## Install

### Linux

```bash
git clone <repository-url> nudge
cd nudge
```

Then **double-click `Nudge.desktop`** in the folder — that file is the
launcher. It locates the program next to itself, so there is nothing to
install, nothing to edit and no absolute path to write in; moving the folder
somewhere else keeps it working. The first start renders the application icon,
which the file then shows from that moment on.

The same thing from a terminal, if you prefer one:

```bash
python3 nudge.py
```

To have Nudge in the application menu as well:

```bash
python3 nudge.py --install-desktop
```

That writes `~/.local/share/applications/nudge.desktop`, inside your own
profile. The **Menu entry** button in the footer does the same thing, and
undoes it.

If tkinter is missing: `sudo apt install python3-tk`

Optional, improves individual techniques:

```bash
sudo apt install python3-xlib python3-dbus python3-evdev xdotool
```

Without `python3-xlib` Nudge falls back to `xdotool`, without `python3-dbus` to
`gdbus`. Only the uinput technique has no substitute.

### Windows

```bat
python -m nudge
```

Or double-click `nudge.pyw` — the `.pyw` extension launches `pythonw.exe`, so
no console window appears. `python -m nudge --install-desktop` puts a shortcut
with an icon in the Start menu, which is the same button in the same place as
on Linux.

**If Python is not installed**, check first:

```bat
python --version
python -c "import tkinter; print('tkinter ok')"
```

Both must succeed. If not, try these in order — none of them needs
administrator rights:

1. **Microsoft Store**, package "Python 3.12". Installs into the user profile,
   includes tkinter, allowed in many corporate environments.
2. **python.org** installer with the *Install for me only* option.
3. **WinPython** as a portable ZIP. Extracted rather than installed, ships
   with tkinter.

Do **not** use the "Windows embeddable package" from python.org — it has no
tkinter and the interface will not start.

---

## Executables

Ready-made single-file executables for Linux and Windows are on the
[Releases page](https://github.com/joruf/nudge/releases). Download the file for
your system (Linux: `chmod +x` it first), no Python needed. The Linux file
carries `python-xlib`; the optional `evdev` and `dbus` integrations need a
source checkout.

To build one yourself, on the system it is meant for:

```bash
python3 build-exe.py      # Linux   -> dist/nudge-linux-x86_64-<version>-build<build>
py build-exe.py           # Windows -> dist/nudge-windows-x86_64-<version>-build<build>.exe
```

The script creates its own build environment in `build/exe/`, installs
PyInstaller and starts the result once with `--version`. Options: `--clean`
rebuilds the environment, `--keep-env` reuses it.

---

## What it looks like

| Light theme | Technique detail and log |
|---|---|
| ![Light theme](docs/images/main-light.png) | ![Detail and log](docs/images/detail-log.png) |

A technique that cannot run on this machine explains why, and what would fix
it:

![Unavailable technique](docs/images/unavailable.png)

---

## Features

- **15 techniques**, 8 for Linux and 7 for Windows, each with its own on/off
  switch and interval
- **Live idle counter** reading `GetLastInputInfo` on Windows and the
  XScreenSaver extension on X11, with a bar filling toward a configurable lock
  threshold
- **Honest availability reporting** — an unusable technique says what is
  missing and gives the exact command to fix it
- **English and German**, switchable at runtime; already-logged lines are
  retranslated too
- **Dark and light theme**
- **Autostart** on both platforms, written into the user profile, no admin
  rights needed
- **Starts by double-click** — `Nudge.desktop` is self-locating, needs no
  installation, and carries an icon that Nudge draws itself, because a machine
  that cannot install a package cannot install an image library either
- **Menu entry** on both platforms — the application menu on Linux, the Start
  menu on Windows — from one button in the footer
- **Headless mode** for running without a window

---

## Documentation

- **[User guide](docs/USER_GUIDE.md)** — the window explained, how to pick a
  technique that works, every technique described, troubleshooting
- **[Technical documentation](docs/TECHNICAL.md)** — architecture, threading
  model, platform APIs, and how to add a technique or a language

---

## Command line

```
python -m nudge                    start the interface
python -m nudge --list             show techniques and their availability
python -m nudge --headless         run without a window
python -m nudge --language de
python -m nudge --install-desktop  add a menu entry with an icon
python -m nudge --remove-desktop   remove it again
```

`python3 nudge.py` does the same as `python -m nudge` and works from any
directory, which is what the menu entry and the autostart entry both point at.
`Nudge.desktop` is the double-click form of the same thing.

---

## A note on scope

Nudge prevents idle locks. Where such a lock is mandated by a corporate
policy, working around it is a matter between you and your IT department —
and for a lasting need, a requested exception is a better route than a tool
that works against the policy.
