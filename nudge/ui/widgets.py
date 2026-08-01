"""Hand-drawn widgets, so the interface looks the same on every platform.

Tk's native widgets differ a lot between Windows and the various Linux themes.
Everything with a visual identity here is therefore drawn on a Canvas: pill
shapes are built from two ovals plus a rectangle, which stays crisp at any
scale instead of the fuzzy edges a smoothed polygon would give.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .theme import Theme

INTERVAL_LADDER = [
    5, 10, 15, 20, 30, 45, 60, 90, 120, 180,
    240, 300, 420, 600, 900, 1200, 1800, 2700, 3600,
]


def draw_pill(canvas: tk.Canvas, x1, y1, x2, y2, fill, outline="", tags=()) -> list[int]:
    """A fully rounded rectangle from two circles and a bridging rectangle."""
    radius = (y2 - y1) / 2
    items = [
        canvas.create_oval(x1, y1, x1 + 2 * radius, y2, fill=fill, outline=outline or fill, tags=tags),
        canvas.create_oval(x2 - 2 * radius, y1, x2, y2, fill=fill, outline=outline or fill, tags=tags),
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill, tags=tags),
    ]
    return items


class Switch(tk.Canvas):
    """An animated on/off toggle."""

    WIDTH = 46
    HEIGHT = 26
    PAD = 3

    def __init__(self, parent, theme: Theme, value: bool = False,
                 command: Callable[[bool], None] | None = None, bg: str | None = None) -> None:
        super().__init__(
            parent,
            width=self.WIDTH,
            height=self.HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=bg or theme.surface,
            cursor="hand2",
        )
        self._theme = theme
        self._value = value
        self._command = command
        self._enabled = True
        self._knob_x = self._target_x()
        self._animating = False
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    # ------------------------------------------------------------- state

    def get(self) -> bool:
        return self._value

    def set(self, value: bool, animate: bool = True, notify: bool = False) -> None:
        value = bool(value)
        if value == self._value:
            return
        self._value = value
        if animate:
            self._animate()
        else:
            self._knob_x = self._target_x()
            self._redraw()
        if notify and self._command:
            self._command(self._value)

    def set_interactive(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def apply_theme(self, theme: Theme, bg: str | None = None) -> None:
        self._theme = theme
        self.configure(bg=bg or theme.surface)
        self._redraw()

    # ---------------------------------------------------------- internals

    def _target_x(self) -> float:
        knob_radius = (self.HEIGHT - 2 * self.PAD) / 2
        return (
            self.WIDTH - self.PAD - knob_radius
            if self._value
            else self.PAD + knob_radius
        )

    def _on_click(self, _event) -> None:
        if not self._enabled:
            return
        self._value = not self._value
        self._animate()
        if self._command:
            self._command(self._value)

    def _animate(self) -> None:
        if self._animating:
            return
        self._animating = True
        self._step()

    def _step(self) -> None:
        target = self._target_x()
        delta = target - self._knob_x
        if abs(delta) < 0.6:
            self._knob_x = target
            self._animating = False
            self._redraw()
            return
        self._knob_x += delta * 0.35
        self._redraw()
        self.after(12, self._step)

    def _redraw(self) -> None:
        self.delete("all")
        theme = self._theme
        if self._value:
            track = theme.accent if self._enabled else theme.border_strong
        else:
            track = theme.track_off
        draw_pill(self, 1, 1, self.WIDTH - 1, self.HEIGHT - 1, track)
        knob_radius = (self.HEIGHT - 2 * self.PAD) / 2
        centre_y = self.HEIGHT / 2
        knob = theme.knob if self._enabled else theme.text_faint
        self.create_oval(
            self._knob_x - knob_radius,
            centre_y - knob_radius,
            self._knob_x + knob_radius,
            centre_y + knob_radius,
            fill=knob,
            outline=knob,
        )


class PillButton(tk.Canvas):
    """A flat rounded button with hover and pressed states."""

    def __init__(self, parent, theme: Theme, text: str, command: Callable[[], None],
                 font, variant: str = "ghost", width: int | None = None,
                 height: int = 30, bg: str | None = None) -> None:
        self._theme = theme
        self._text = text
        self._variant = variant
        self._command = command
        self._font = font
        self._hover = False
        self._pressed = False
        self._enabled = True
        self._parent_bg = bg or theme.surface
        # A caller-supplied width is respected verbatim; auto-sized buttons
        # re-measure whenever their label changes.
        self._fixed_width = width is not None
        measured = width or (self._measure(text) + 28)
        super().__init__(
            parent,
            width=measured,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=self._parent_bg,
            cursor="hand2",
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def _measure(self, text: str) -> int:
        from tkinter import font as tkfont

        try:
            return tkfont.Font(font=self._font).measure(text)
        except tk.TclError:
            return 8 * len(text)

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        if not self._fixed_width:
            self.configure(width=self._measure(text) + 28)
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def apply_theme(self, theme: Theme, bg: str | None = None) -> None:
        self._theme = theme
        self._parent_bg = bg or theme.surface
        self.configure(bg=self._parent_bg)
        self._redraw()

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._redraw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._pressed = False
        self._redraw()

    def _on_press(self, _e) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self._redraw()

    def _on_release(self, _e) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if was_pressed and self._enabled and self._command:
            self._command()

    def _colours(self) -> tuple[str, str, str]:
        theme = self._theme
        if not self._enabled:
            return theme.surface_sunken, theme.text_faint, theme.border
        if self._variant == "accent":
            fill = theme.accent_hover if self._hover else theme.accent
            if self._pressed:
                fill = theme.accent
            return fill, theme.accent_text, fill
        if self._variant == "danger":
            fill = theme.surface_hover if self._hover else theme.surface
            return fill, theme.danger, theme.border_strong
        fill = theme.surface_hover if self._hover else theme.surface
        if self._pressed:
            fill = theme.surface_sunken
        return fill, theme.text_muted, theme.border

    def _redraw(self) -> None:
        self.delete("all")
        fill, text_colour, outline = self._colours()
        width = int(self["width"])
        height = int(self["height"])
        draw_pill(self, 1, 1, width - 1, height - 1, fill, outline=outline)
        # Redraw the outline as a stroked pill so the border stays visible.
        radius = (height - 2) / 2
        self.create_arc(1, 1, 1 + 2 * radius, height - 1, start=90, extent=180,
                        style=tk.ARC, outline=outline)
        self.create_arc(width - 1 - 2 * radius, 1, width - 1, height - 1, start=-90,
                        extent=180, style=tk.ARC, outline=outline)
        self.create_line(1 + radius, 1, width - 1 - radius, 1, fill=outline)
        self.create_line(1 + radius, height - 1, width - 1 - radius, height - 1, fill=outline)
        self.create_text(width / 2, height / 2, text=self._text, fill=text_colour,
                         font=self._font)


class IntervalSpinner(tk.Frame):
    """Minus / value / plus stepper that also accepts typed numbers."""

    def __init__(self, parent, theme: Theme, fonts, value: int,
                 on_change: Callable[[int], None], bg: str | None = None) -> None:
        self._theme = theme
        self._bg = bg or theme.surface
        super().__init__(parent, bg=self._bg)
        self._fonts = fonts
        self._value = value
        self._on_change = on_change

        self._minus = PillButton(self, theme, "−", self._decrement, fonts.body,
                                 width=26, height=24, bg=self._bg)
        self._minus.pack(side="left")

        self._var = tk.StringVar(value=str(value))
        self._entry = tk.Entry(
            self,
            textvariable=self._var,
            width=5,
            justify="center",
            font=fonts.body,
            bg=theme.surface_sunken,
            fg=theme.text,
            insertbackground=theme.text,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.border,
            highlightcolor=theme.accent,
        )
        self._entry.pack(side="left", padx=4, ipady=2)
        self._entry.bind("<Return>", self._commit_typed)
        self._entry.bind("<FocusOut>", self._commit_typed)

        self._plus = PillButton(self, theme, "+", self._increment, fonts.body,
                                width=26, height=24, bg=self._bg)
        self._plus.pack(side="left")

        self._unit = tk.Label(self, text="s", font=fonts.small, bg=self._bg,
                              fg=theme.text_faint)
        self._unit.pack(side="left", padx=(5, 0))

    def get(self) -> int:
        return self._value

    def set(self, value: int) -> None:
        self._value = int(value)
        self._var.set(str(self._value))

    def apply_theme(self, theme: Theme, bg: str | None = None) -> None:
        self._theme = theme
        self._bg = bg or theme.surface
        self.configure(bg=self._bg)
        self._minus.apply_theme(theme, self._bg)
        self._plus.apply_theme(theme, self._bg)
        self._unit.configure(bg=self._bg, fg=theme.text_faint)
        self._entry.configure(
            bg=theme.surface_sunken,
            fg=theme.text,
            insertbackground=theme.text,
            highlightbackground=theme.border,
            highlightcolor=theme.accent,
        )

    # ---------------------------------------------------------- internals

    def _emit(self) -> None:
        self._var.set(str(self._value))
        self._on_change(self._value)

    def _increment(self) -> None:
        for step in INTERVAL_LADDER:
            if step > self._value:
                self._value = step
                break
        else:
            self._value = INTERVAL_LADDER[-1]
        self._emit()

    def _decrement(self) -> None:
        for step in reversed(INTERVAL_LADDER):
            if step < self._value:
                self._value = step
                break
        else:
            self._value = INTERVAL_LADDER[0]
        self._emit()

    def _commit_typed(self, _event=None) -> None:
        raw = self._var.get().strip()
        try:
            parsed = int(raw)
        except ValueError:
            self._var.set(str(self._value))
            return
        parsed = max(INTERVAL_LADDER[0], min(INTERVAL_LADDER[-1], parsed))
        if parsed != self._value:
            self._value = parsed
            self._emit()
        else:
            self._var.set(str(self._value))


class ScrollFrame(tk.Frame):
    """Vertically scrollable container with a slim, self-drawn scrollbar."""

    BAR_WIDTH = 8

    def __init__(self, parent, theme: Theme) -> None:
        self._theme = theme
        super().__init__(parent, bg=theme.bg)

        self._canvas = tk.Canvas(self, bg=theme.bg, highlightthickness=0, bd=0)
        self._canvas.pack(side="left", fill="both", expand=True)

        self._bar = tk.Canvas(self, width=self.BAR_WIDTH, bg=theme.bg,
                              highlightthickness=0, bd=0)
        self._bar.pack(side="right", fill="y")

        self.interior = tk.Frame(self._canvas, bg=theme.bg)
        self._window = self._canvas.create_window(
            (0, 0), window=self.interior, anchor="nw"
        )

        self.interior.bind("<Configure>", self._on_interior_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self)
        self._drag_origin: tuple[float, float] | None = None
        self._bar.bind("<Button-1>", self._on_bar_press)
        self._bar.bind("<B1-Motion>", self._on_bar_drag)
        self._bar.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag_origin", None))

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.configure(bg=theme.bg)
        self._canvas.configure(bg=theme.bg)
        self._bar.configure(bg=theme.bg)
        self.interior.configure(bg=theme.bg)
        self._draw_bar()

    # ------------------------------------------------------------ wheel

    def _bind_wheel(self, widget) -> None:
        # Windows and macOS deliver <MouseWheel>; X11 sends buttons 4 and 5.
        widget.bind_all("<MouseWheel>", self._on_wheel, add="+")
        widget.bind_all("<Button-4>", self._on_wheel, add="+")
        widget.bind_all("<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event) -> None:
        if not self._pointer_inside():
            return
        if getattr(event, "num", None) == 4:
            delta = -3
        elif getattr(event, "num", None) == 5:
            delta = 3
        else:
            delta = -int(event.delta / 40) if abs(event.delta) < 200 else -int(event.delta / 120) * 3
        self._canvas.yview_scroll(delta, "units")
        self._draw_bar()

    def _pointer_inside(self) -> bool:
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    # -------------------------------------------------------- geometry

    def _on_interior_configure(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._draw_bar()

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)
        self._draw_bar()

    def _draw_bar(self) -> None:
        self._bar.delete("all")
        first, last = self._canvas.yview()
        height = self._bar.winfo_height()
        if height <= 1 or (first <= 0.0 and last >= 1.0):
            return
        top = first * height
        bottom = max(last * height, top + 24)
        draw_pill(self._bar, 1, top, self.BAR_WIDTH - 1, min(bottom, height),
                  self._theme.border_strong)

    def _on_bar_press(self, event) -> None:
        self._drag_origin = (event.y, self._canvas.yview()[0])
        self._jump_to(event.y)

    def _on_bar_drag(self, event) -> None:
        self._jump_to(event.y)

    def _jump_to(self, y: float) -> None:
        height = max(1, self._bar.winfo_height())
        first, last = self._canvas.yview()
        span = max(0.02, last - first)
        fraction = max(0.0, min(1.0, (y / height) - span / 2))
        self._canvas.yview_moveto(fraction)
        self._draw_bar()

    def refresh_scrollbar(self) -> None:
        self._draw_bar()
