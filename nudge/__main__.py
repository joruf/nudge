"""Entry point: python -m nudge [--list] [--headless] [--language de]"""

from __future__ import annotations

import argparse
import sys
import time


# --- what this application needs ----------------------------------------------------------------
# Checked before anything below is imported. Whatever is missing is installed in a window that
# shows the work as it happens; see bootstrap_ui.py. `--setup` opens that window even when nothing
# is missing, which is how to see what is installed.
from .bootstrap_ui import Need, ensure  # noqa: E402

NEEDS = (
    Need(label="X11 bindings", module="Xlib", packages=("python3-xlib",), optional=True,
         note="idle time is measured less precisely"),
    Need(label="Input device access", module="evdev", packages=("python3-evdev",), optional=True,
         note="key and mouse activity is not seen"),
    Need(label="Desktop bus", module="dbus", packages=("python3-dbus",), optional=True,
         note="the screensaver state is not seen"),
    Need(label="Pointer tools", command="xdotool", packages=("xdotool",), optional=True,
         note="the pointer cannot be nudged"),
)

# Only when the application is actually being started. Importing this module — which the test
# suite does — should not check anything, let alone put an installer window on screen.
if __name__ == "__main__":
    # Taken out of the arguments once it has been read, so the application's own parser does
    # not trip over a flag that was never meant for it.
    _SETUP = "--setup" in sys.argv

    if _SETUP:
        sys.argv.remove("--setup")

    if not ensure("Nudge", NEEDS, force=_SETUP):
        raise SystemExit(1)

from . import APP_NAME, VERSION_LABEL
from . import desktop_entry
from .config import Config
from .eventlog import EventLog
from .i18n import DEFAULT_LANGUAGE, available_languages, set_language, t
from .idle import IdleMonitor, format_idle
from .scheduler import Scheduler
from .sysinfo import detect_vm, platform_label
from .techniques import load_techniques


def cmd_list() -> int:
    print(f"{APP_NAME} {VERSION_LABEL} — {platform_label()}")
    vm = detect_vm()
    if vm:
        print(t("cli.virtualisation", vm=vm))
    monitor = IdleMonitor()
    print(t("cli.idle_backend", backend=monitor.backend_name))
    print()
    techniques = load_techniques()
    if not techniques:
        print(t("cli.no_techniques"))
        return 1
    for technique in techniques:
        availability = technique.availability()
        mark = "+" if availability.ok else "-"
        note = availability.reason or (t("avail.available") if availability.ok else "")
        print(f" {mark} {technique.id:26} {technique.name}")
        print(f"     {technique.summary}")
        print(f"     {technique.interval_label} {technique.default_interval}s · {note}")
        if not availability.ok and availability.hint:
            print(f"     {t('cli.remedy', hint=availability.hint)}")
        print()
    return 0


def cmd_desktop(install: bool) -> int:
    """Add Nudge to the desktop's own list of programs, or take it out again.

    Args:
        install: True to create the entry, False to remove it.

    Returns:
        int: Process exit status.
    """
    if not desktop_entry.supported():
        print(t("log.entry_unsupported"), file=sys.stderr)
        return 2
    ok, key, params = desktop_entry.set_installed(install)
    print(t(key, **params), file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_headless(duration: float | None) -> int:
    config = Config()
    log = EventLog()
    techniques = load_techniques()
    scheduler = Scheduler(techniques, config, log)
    monitor = IdleMonitor()
    scheduler.start()
    scheduler.set_master(True)
    enabled = [
        technique.name
        for technique in techniques
        if config.is_enabled(technique.id, technique.default_enabled)
        and technique.availability().ok
    ]
    print(t("cli.headless_running", app=APP_NAME,
            techniques=", ".join(enabled) or t("cli.headless_nothing")))
    print(t("cli.headless_quit"))
    print()
    started = time.monotonic()
    seen = 0
    try:
        while duration is None or (time.monotonic() - started) < duration:
            time.sleep(1.0)
            entries = log.tail(50)
            for entry in entries[seen:]:
                print(f"{entry.clock()}  {entry.source_text()}: {entry.text()}")
            seen = len(entries)
            print(f"\r{t('cli.idle_label')} {format_idle(monitor.seconds()):>10}",
                  end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        scheduler.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    config = Config()
    # The saved language applies to --help too, so parse it from the
    # environment of the config before argparse builds its texts.
    set_language(config.get("language", DEFAULT_LANGUAGE))

    codes = [code for code, _ in available_languages()]
    parser = argparse.ArgumentParser(
        prog="nudge", description=t("cli.description", app=APP_NAME)
    )
    parser.add_argument("--list", action="store_true", help=t("cli.arg_list"))
    parser.add_argument("--headless", action="store_true", help=t("cli.arg_headless"))
    parser.add_argument("--duration", type=float, default=None,
                        help=t("cli.arg_duration"))
    parser.add_argument("--language", "--lang", dest="language", choices=codes,
                        default=None, help=t("cli.arg_language"))
    parser.add_argument("--install-desktop", action="store_true",
                        help=t("cli.arg_install_desktop"))
    parser.add_argument("--remove-desktop", action="store_true",
                        help=t("cli.arg_remove_desktop"))
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION_LABEL}")
    args = parser.parse_args(argv)

    if args.language:
        set_language(args.language)
        config.set("language", args.language)
        config.save()

    if args.install_desktop or args.remove_desktop:
        return cmd_desktop(args.install_desktop)
    if args.list:
        return cmd_list()
    if args.headless:
        return cmd_headless(args.duration)

    try:
        from .ui.app import main as ui_main
    except ImportError as exc:
        print(t("cli.needs_tk", error=exc), file=sys.stderr)
        print(t("cli.install_tk"), file=sys.stderr)
        print(t("cli.headless_hint"), file=sys.stderr)
        return 2
    return ui_main()


if __name__ == "__main__":
    sys.exit(main())
