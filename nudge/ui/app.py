"""The Nudge main window."""

from __future__ import annotations

import time
import tkinter as tk

from .. import APP_NAME, __version__
from .. import autostart
from ..config import Config
from ..eventlog import EventLog
from ..i18n import (
    DEFAULT_LANGUAGE,
    available_languages,
    current_language,
    set_language,
    t,
)
from ..idle import IdleMonitor, format_idle
from ..scheduler import Scheduler, Snapshot
from ..sysinfo import detect_vm, platform_label
from ..techniques import SUSTAINED, Technique, load_techniques
from .theme import THEMES, Fonts, Theme
from .widgets import IntervalSpinner, PillButton, ScrollFrame, Switch, draw_pill

REFRESH_MS = 500
DEFAULT_THRESHOLD = 300


def relative_time(timestamp: float | None) -> str:
    if timestamp is None:
        return t("card.never")
    delta = max(0, int(time.time() - timestamp))
    if delta < 60:
        return t("card.ago_seconds", value=delta)
    if delta < 3600:
        return t("card.ago_minutes", value=delta // 60)
    return t("card.ago_hours", value=delta // 3600)


class IdleMeter(tk.Frame):
    """Large idle readout plus a bar filling toward the lock threshold.

    This is the app's feedback loop: if the number keeps returning to zero,
    the enabled techniques are genuinely reaching the system's idle timer.
    """

    BAR_HEIGHT = 6

    def __init__(self, parent, theme: Theme, fonts: Fonts, monitor: IdleMonitor,
                 threshold: int, on_threshold_change) -> None:
        self._theme = theme
        self._fonts = fonts
        self._monitor = monitor
        self._threshold = threshold
        super().__init__(parent, bg=theme.surface)

        top = tk.Frame(self, bg=theme.surface)
        top.pack(fill="x")

        self._value = tk.Label(top, text=t("time.unknown"), font=fonts.metric,
                               bg=theme.surface, fg=theme.text, anchor="w")
        self._value.pack(side="left")

        text_column = tk.Frame(top, bg=theme.surface)
        text_column.pack(side="left", padx=(10, 0), pady=(6, 0))
        self._caption = tk.Label(text_column, text=t("header.idle"), font=fonts.small,
                                 bg=theme.surface, fg=theme.text_muted, anchor="w")
        self._caption.pack(anchor="w")
        self._backend = tk.Label(text_column, text=monitor.backend_name, font=fonts.tiny,
                                 bg=theme.surface, fg=theme.text_faint, anchor="w")
        self._backend.pack(anchor="w")

        threshold_box = tk.Frame(top, bg=theme.surface)
        threshold_box.pack(side="right", pady=(4, 0))
        self._threshold_label = tk.Label(threshold_box, text=t("header.threshold"),
                                         font=fonts.tiny, bg=theme.surface,
                                         fg=theme.text_faint)
        self._threshold_label.pack(anchor="e")
        self._spinner = IntervalSpinner(threshold_box, theme, fonts, threshold,
                                        on_threshold_change, bg=theme.surface)
        self._spinner.pack(anchor="e", pady=(2, 0))

        self._bar = tk.Canvas(self, height=self.BAR_HEIGHT, bg=theme.surface,
                              highlightthickness=0, bd=0)
        self._bar.pack(fill="x", pady=(10, 0))
        self._bar.bind("<Configure>", lambda _e: self._draw_bar(self._last_seconds))
        self._last_seconds = -1.0

    def set_threshold(self, seconds: int) -> None:
        self._threshold = max(10, seconds)
        self._draw_bar(self._last_seconds)

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        for widget in (self, self._value.master, self._caption.master):
            widget.configure(bg=theme.surface)
        self._value.configure(bg=theme.surface, fg=theme.text)
        self._caption.configure(bg=theme.surface, fg=theme.text_muted)
        self._backend.configure(bg=theme.surface, fg=theme.text_faint)
        self._threshold_label.master.configure(bg=theme.surface)
        self._threshold_label.configure(bg=theme.surface, fg=theme.text_faint)
        self._spinner.apply_theme(theme, theme.surface)
        self._bar.configure(bg=theme.surface)
        self._draw_bar(self._last_seconds)

    def refresh(self) -> float:
        seconds = self._monitor.seconds()
        self._last_seconds = seconds
        self._value.configure(text=format_idle(seconds), fg=self._colour(seconds))
        self._draw_bar(seconds)
        return seconds

    def _colour(self, seconds: float) -> str:
        if seconds < 0:
            return self._theme.text_faint
        ratio = seconds / max(1, self._threshold)
        if ratio < 0.5:
            return self._theme.ok
        if ratio < 0.85:
            return self._theme.warn
        return self._theme.danger

    def _draw_bar(self, seconds: float) -> None:
        self._bar.delete("all")
        width = self._bar.winfo_width()
        if width <= 1:
            return
        draw_pill(self._bar, 0, 0, width, self.BAR_HEIGHT, self._theme.surface_sunken)
        if seconds < 0:
            return
        ratio = min(1.0, seconds / max(1, self._threshold))
        filled = max(self.BAR_HEIGHT, width * ratio)
        draw_pill(self._bar, 0, 0, filled, self.BAR_HEIGHT, self._colour(seconds))


class TechniqueCard(tk.Frame):
    """One technique: toggle, interval, live status and an expandable detail."""

    def __init__(self, parent, theme: Theme, fonts: Fonts, technique: Technique,
                 enabled: bool, interval: int, on_toggle, on_interval, on_fire) -> None:
        self._theme = theme
        self._fonts = fonts
        self.technique = technique
        self._expanded = False
        self._on_fire = on_fire
        super().__init__(parent, bg=theme.surface, highlightthickness=1,
                         highlightbackground=theme.border, bd=0)

        inner = tk.Frame(self, bg=theme.surface)
        inner.pack(fill="x", padx=14, pady=12)
        self._inner = inner

        # --- title row -----------------------------------------------
        title_row = tk.Frame(inner, bg=theme.surface)
        title_row.pack(fill="x")

        titles = tk.Frame(title_row, bg=theme.surface)
        titles.pack(side="left", fill="x", expand=True)
        self._name = tk.Label(titles, text=technique.name, font=fonts.heading,
                              bg=theme.surface, fg=theme.text, anchor="w", cursor="hand2")
        self._name.pack(anchor="w")
        self._summary = tk.Label(titles, text=technique.summary, font=fonts.small,
                                 bg=theme.surface, fg=theme.text_muted, anchor="w",
                                 justify="left", cursor="hand2")
        self._summary.pack(anchor="w", pady=(2, 0))

        self._switch = Switch(title_row, theme, enabled, on_toggle, bg=theme.surface)
        self._switch.pack(side="right", padx=(12, 0))

        for widget in (self._name, self._summary):
            widget.bind("<Button-1>", self._toggle_detail)

        # --- detail paragraph, hidden until the title is clicked ------
        self._detail = tk.Label(inner, text=technique.detail, font=fonts.small,
                                bg=theme.surface_sunken, fg=theme.text_muted,
                                anchor="w", justify="left", padx=10, pady=8)

        # --- controls row ---------------------------------------------
        controls = tk.Frame(inner, bg=theme.surface)
        controls.pack(fill="x", pady=(10, 0))
        self._controls = controls

        self._interval_label = tk.Label(controls, text=technique.interval_label,
                                        font=fonts.tiny, bg=theme.surface,
                                        fg=theme.text_faint)
        self._interval_label.pack(side="left", padx=(0, 6))
        self._spinner = IntervalSpinner(controls, theme, fonts, interval, on_interval,
                                        bg=theme.surface)
        self._spinner.pack(side="left")

        self._fire_button = PillButton(controls, theme, t("card.now"),
                                       self._fire_clicked, fonts.small, height=24,
                                       bg=theme.surface)
        self._fire_button.pack(side="right")

        # --- status line ----------------------------------------------
        self._status = tk.Label(inner, text="", font=fonts.tiny, bg=theme.surface,
                                fg=theme.text_faint, anchor="w", justify="left")
        self._status.pack(fill="x", pady=(8, 0))

        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------ events

    def _fire_clicked(self) -> None:
        self._on_fire(self.technique.id)

    def _toggle_detail(self, _event=None) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._detail.pack(fill="x", pady=(10, 0), before=self._controls)
        else:
            self._detail.pack_forget()

    def _on_resize(self, event) -> None:
        wrap = max(200, event.width - 60)
        self._detail.configure(wraplength=wrap)
        self._summary.configure(wraplength=wrap)
        self._status.configure(wraplength=wrap)

    # ------------------------------------------------------------ render

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        surface = theme.surface
        self.configure(bg=surface, highlightbackground=theme.border)
        for frame in (self._inner, self._controls):
            frame.configure(bg=surface)
        self._name.master.configure(bg=surface)
        self._name.master.master.configure(bg=surface)
        self._name.configure(bg=surface, fg=theme.text)
        self._summary.configure(bg=surface, fg=theme.text_muted)
        self._detail.configure(bg=theme.surface_sunken, fg=theme.text_muted)
        self._interval_label.configure(bg=surface, fg=theme.text_faint)
        self._status.configure(bg=surface)
        self._switch.apply_theme(theme, surface)
        self._spinner.apply_theme(theme, surface)
        self._fire_button.apply_theme(theme, surface)

    def update_state(self, snapshot: Snapshot, master_active: bool) -> None:
        theme = self._theme
        availability = self.technique.availability()

        if not availability.ok:
            self._switch.set_interactive(False)
            self._fire_button.set_enabled(False)
            text = t("card.unavailable", reason=availability.reason)
            if availability.hint:
                text = f"{text}  ·  {availability.hint}"
            self._status.configure(text=text, fg=theme.warn)
            self._name.configure(fg=theme.text_muted)
            return

        self._switch.set_interactive(True)
        self._name.configure(fg=theme.text)
        if self._switch.get() != snapshot.enabled:
            self._switch.set(snapshot.enabled)
        if self._spinner.get() != snapshot.interval:
            self._spinner.set(snapshot.interval)
        self._fire_button.set_enabled(True)

        if snapshot.error:
            self._status.configure(text=t("card.error", error=snapshot.error),
                                   fg=theme.danger)
            return

        if not snapshot.enabled:
            self._status.configure(text=t("card.disabled"), fg=theme.text_faint)
            return

        if not master_active:
            self._status.configure(text=t("card.ready_paused"), fg=theme.text_faint)
            return

        parts = [str(snapshot.last_status) or t("card.active"),
                 relative_time(snapshot.last_fired)]
        if snapshot.seconds_until_next is not None:
            seconds = int(snapshot.seconds_until_next)
            key = "card.check_in" if self.technique.kind == SUSTAINED else "card.next_in"
            parts.append(t(key, seconds=seconds))
        self._status.configure(text="  ·  ".join(parts), fg=theme.ok)


class NudgeApp:
    def __init__(self) -> None:
        self.config = Config()
        set_language(self.config.get("language", DEFAULT_LANGUAGE))
        self.log = EventLog()
        self.techniques = load_techniques()
        self.scheduler = Scheduler(self.techniques, self.config, self.log)
        self.idle_monitor = IdleMonitor()
        self.theme: Theme = THEMES.get(self.config.get("theme", "dark"), THEMES["dark"])

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.minsize(560, 560)
        geometry = self.config.get("geometry")
        self.root.geometry(geometry if geometry else "600x780")
        self.fonts = Fonts(self.root)
        self.root.configure(bg=self.theme.bg)

        self._cards: dict[str, TechniqueCard] = {}
        self._log_visible = bool(self.config.get("log_expanded", False))
        self._log_revision = -1

        self._build()
        self.scheduler.start()
        if self.config.get("master_active", False):
            self._set_master(True)
        self._refresh()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.techniques:
            self.log.warn(t("log.source_app"), t("log.no_techniques"))

    # -------------------------------------------------------------- build

    def _build(self) -> None:
        theme = self.theme
        self._header = tk.Frame(self.root, bg=theme.surface)
        self._header.pack(fill="x")
        self._header_border = tk.Frame(self.root, bg=theme.border, height=1)
        self._header_border.pack(fill="x")

        header_inner = tk.Frame(self._header, bg=theme.surface)
        header_inner.pack(fill="x", padx=18, pady=16)
        self._header_inner = header_inner

        top_row = tk.Frame(header_inner, bg=theme.surface)
        top_row.pack(fill="x")
        self._top_row = top_row

        titles = tk.Frame(top_row, bg=theme.surface)
        titles.pack(side="left")
        self._titles = titles
        self._title = tk.Label(titles, text=APP_NAME, font=self.fonts.title,
                               bg=theme.surface, fg=theme.text, anchor="w")
        self._title.pack(anchor="w")
        self._subtitle = tk.Label(titles, text=platform_label(), font=self.fonts.small,
                                  bg=theme.surface, fg=theme.text_muted, anchor="w")
        self._subtitle.pack(anchor="w")

        master_box = tk.Frame(top_row, bg=theme.surface)
        master_box.pack(side="right")
        self._master_box = master_box
        switch_row = tk.Frame(master_box, bg=theme.surface)
        switch_row.pack(anchor="e")
        self._switch_row = switch_row
        self._master_label = tk.Label(switch_row, text=t("header.paused"),
                                      font=self.fonts.small, bg=theme.surface,
                                      fg=theme.text_muted)
        self._master_label.pack(side="left", padx=(0, 10))
        self._master_switch = Switch(switch_row, theme, False, self._set_master,
                                     bg=theme.surface)
        self._master_switch.pack(side="left")
        self._summary_label = tk.Label(master_box, text="", font=self.fonts.tiny,
                                       bg=theme.surface, fg=theme.text_faint)
        self._summary_label.pack(anchor="e", pady=(6, 0))

        self._meter = IdleMeter(header_inner, theme, self.fonts, self.idle_monitor,
                                int(self.config.get("lock_threshold", DEFAULT_THRESHOLD)),
                                self._on_threshold_change)
        self._meter.pack(fill="x", pady=(16, 0))

        self._banner: tk.Label | None = None
        vm = detect_vm()
        if vm:
            self._banner = tk.Label(
                self.root, text=t("banner.vm", vm=vm), font=self.fonts.small,
                bg=theme.surface_sunken, fg=theme.warn, justify="left", anchor="w",
                padx=16, pady=10,
            )
            self._banner.pack(fill="x")
            self._banner.bind(
                "<Configure>",
                lambda e: self._banner.configure(wraplength=max(200, e.width - 40)),
            )

        self._body = ScrollFrame(self.root, theme)
        self._body.pack(fill="both", expand=True)

        for technique in self.techniques:
            card = TechniqueCard(
                self._body.interior, theme, self.fonts, technique,
                enabled=self.config.is_enabled(technique.id, technique.default_enabled),
                interval=self.config.interval(technique.id, technique.default_interval),
                on_toggle=lambda value, tid=technique.id: self._toggle(tid, value),
                on_interval=lambda value, tid=technique.id: self.scheduler.set_interval(tid, value),
                on_fire=self.scheduler.fire_now,
            )
            card.pack(fill="x", padx=16, pady=6)
            self._cards[technique.id] = card

        self._build_footer()

    def _build_footer(self) -> None:
        theme = self.theme
        # One bottom container packed top-down, so the separator, the log panel
        # and the button row always keep their order regardless of what is
        # currently shown.
        self._bottom = tk.Frame(self.root, bg=theme.bg)
        self._bottom.pack(fill="x", side="bottom")

        self._footer_border = tk.Frame(self._bottom, bg=theme.border, height=1)
        self._footer_border.pack(fill="x", side="top")

        self._log_frame = tk.Frame(self._bottom, bg=theme.surface_sunken)
        self._log_text = tk.Text(
            self._log_frame, height=7, font=self.fonts.mono, bg=theme.surface_sunken,
            fg=theme.text_muted, relief="flat", highlightthickness=0, wrap="word",
            padx=12, pady=8, state="disabled",
        )
        self._log_text.pack(fill="both", expand=True)
        self._configure_log_tags()

        self._footer = tk.Frame(self._bottom, bg=theme.surface)
        self._footer.pack(fill="x", side="top")
        row = tk.Frame(self._footer, bg=theme.surface)
        row.pack(fill="x", padx=16, pady=10)
        self._footer_row = row

        self._log_button = PillButton(row, theme, t("footer.log"), self._toggle_log,
                                      self.fonts.small, height=28, bg=theme.surface)
        self._log_button.pack(side="left")

        self._autostart_button = PillButton(row, theme, t("footer.autostart_off"),
                                            self._toggle_autostart, self.fonts.small,
                                            height=28, bg=theme.surface)
        self._autostart_button.pack(side="left", padx=(8, 0))
        self._sync_autostart_label()

        self._theme_button = PillButton(row, theme, self._theme_label(),
                                        self._toggle_theme, self.fonts.small,
                                        height=28, bg=theme.surface)
        self._theme_button.pack(side="right")

        self._language_button = PillButton(row, theme, self._language_label(),
                                           self._cycle_language, self.fonts.small,
                                           height=28, bg=theme.surface)
        self._language_button.pack(side="right", padx=(0, 8))

        if self._log_visible:
            self._log_frame.pack(fill="x", side="top", before=self._footer)

    def _configure_log_tags(self) -> None:
        theme = self.theme
        for level, colour in (
            ("info", theme.text_muted), ("ok", theme.ok),
            ("warn", theme.warn), ("error", theme.danger),
        ):
            self._log_text.tag_configure(level, foreground=colour)

    # ------------------------------------------------------------ actions

    def _toggle(self, tech_id: str, value: bool) -> None:
        self.scheduler.set_enabled(tech_id, value)

    def _set_master(self, active: bool) -> None:
        self.scheduler.set_master(active)
        if self._master_switch.get() != active:
            self._master_switch.set(active)
        self._master_label.configure(
            text=t("header.active") if active else t("header.paused"),
            fg=self.theme.ok if active else self.theme.text_muted,
        )

    def _on_threshold_change(self, seconds: int) -> None:
        self.config.set("lock_threshold", seconds)
        self.config.save()
        self._meter.set_threshold(seconds)

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self._log_frame.pack(fill="x", side="top", before=self._footer)
        else:
            self._log_frame.pack_forget()
        self.config.set("log_expanded", self._log_visible)
        self.config.save()

    def _toggle_autostart(self) -> None:
        target = not autostart.is_enabled()
        ok, key, params = autostart.set_enabled(target)
        (self.log.ok if ok else self.log.error)(t("log.autostart"), t(key, **params))
        self._sync_autostart_label()

    def _sync_autostart_label(self) -> None:
        active = autostart.is_enabled()
        self._autostart_button.set_text(
            t("footer.autostart_on") if active else t("footer.autostart_off")
        )
        self._autostart_button.set_enabled(autostart.supported())

    def _theme_label(self) -> str:
        # Words rather than sun/moon symbols: those are missing from several
        # default UI fonts and render as a replacement box.
        return t("footer.theme_light") if self.theme.is_dark else t("footer.theme_dark")

    def _toggle_theme(self) -> None:
        self.theme = THEMES["light" if self.theme.is_dark else "dark"]
        self.config.set("theme", self.theme.name)
        self.config.save()
        self._apply_theme()

    def _language_label(self) -> str:
        code = current_language()
        for candidate, label in available_languages():
            if candidate == code:
                return label
        return code.upper()

    def _cycle_language(self) -> None:
        languages = available_languages()
        codes = [code for code, _ in languages]
        try:
            index = codes.index(current_language())
        except ValueError:
            index = -1
        code = codes[(index + 1) % len(codes)]
        set_language(code)
        self.config.set("language", code)
        self.config.save()
        self.log.info(t("log.source_app"),
                      t("log.language_changed", language=self._language_label()))
        self._rebuild()

    def _rebuild(self) -> None:
        """Recreate the window contents, e.g. after the language changed.

        Rebuilding is simpler and less error-prone than threading a language
        update through every widget, and the scheduler keeps running
        untouched while it happens.
        """
        for child in self.root.winfo_children():
            child.destroy()
        self._cards.clear()
        self._build()
        self._set_master(self.scheduler.master_active)
        self._log_revision = -1

    def _apply_theme(self) -> None:
        theme = self.theme
        self.root.configure(bg=theme.bg)
        for frame in (self._header, self._header_inner, self._top_row, self._titles,
                      self._master_box, self._switch_row, self._footer,
                      self._footer_row):
            frame.configure(bg=theme.surface)
        self._bottom.configure(bg=theme.bg)
        self._header_border.configure(bg=theme.border)
        self._footer_border.configure(bg=theme.border)
        self._title.configure(bg=theme.surface, fg=theme.text)
        self._subtitle.configure(bg=theme.surface, fg=theme.text_muted)
        self._master_label.configure(bg=theme.surface)
        self._master_switch.apply_theme(theme, theme.surface)
        self._summary_label.configure(bg=theme.surface, fg=theme.text_faint)
        self._meter.apply_theme(theme)
        if self._banner is not None:
            self._banner.configure(bg=theme.surface_sunken, fg=theme.warn)
        self._body.apply_theme(theme)
        for card in self._cards.values():
            card.apply_theme(theme)
        self._log_frame.configure(bg=theme.surface_sunken)
        self._log_text.configure(bg=theme.surface_sunken, fg=theme.text_muted)
        self._configure_log_tags()
        for button in (self._log_button, self._autostart_button,
                       self._language_button, self._theme_button):
            button.apply_theme(theme, theme.surface)
        self._theme_button.set_text(self._theme_label())
        self._set_master(self.scheduler.master_active)
        self._log_revision = -1  # force a redraw with the new tag colours

    # ------------------------------------------------------------ refresh

    def _refresh(self) -> None:
        self._meter.refresh()
        snapshots = self.scheduler.snapshots()
        master = self.scheduler.master_active
        for tech_id, card in self._cards.items():
            snapshot = snapshots.get(tech_id)
            if snapshot is not None:
                card.update_state(snapshot, master)
        self._summary_label.configure(
            text=t("footer.summary", active=self.scheduler.active_count(),
                   total=len(self.techniques))
        )
        self._body.refresh_scrollbar()
        if self._log_visible:
            self._redraw_log()
        self.root.after(REFRESH_MS, self._refresh)

    def _redraw_log(self) -> None:
        revision = self.log.revision()
        if revision == self._log_revision:
            return
        self._log_revision = revision
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        for entry in self.log.tail(150):
            self._log_text.insert(
                "end", f"{entry.clock()}  {entry.source_text()}: {entry.text()}\n",
                entry.level,
            )
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # -------------------------------------------------------------- close

    def _on_close(self) -> None:
        try:
            self.config.set("geometry", self.root.winfo_geometry())
            self.config.save()
        except Exception:
            pass
        self.scheduler.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = NudgeApp()
    app.run()
    return 0
