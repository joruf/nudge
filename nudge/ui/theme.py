"""Colour palettes and font selection for the interface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    surface: str
    surface_hover: str
    surface_sunken: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_text: str
    ok: str
    warn: str
    danger: str
    track_off: str
    knob: str
    shadow: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


DARK = Theme(
    name="dark",
    bg="#0e1014",
    surface="#171a21",
    surface_hover="#1d212a",
    surface_sunken="#101318",
    border="#252a34",
    border_strong="#333a47",
    text="#e7eaf0",
    text_muted="#98a1b3",
    text_faint="#6a7385",
    accent="#4f8cff",
    accent_hover="#6d9fff",
    accent_text="#ffffff",
    ok="#3ecf8e",
    warn="#f0b429",
    danger="#f2545b",
    track_off="#333a47",
    knob="#ffffff",
    shadow="#0a0c0f",
)

LIGHT = Theme(
    name="light",
    bg="#f4f5f7",
    surface="#ffffff",
    surface_hover="#f7f8fa",
    surface_sunken="#eef0f4",
    border="#e0e4ea",
    border_strong="#c9cfd9",
    text="#161a22",
    text_muted="#5d6675",
    text_faint="#8a93a3",
    accent="#2f6feb",
    accent_hover="#1f5fd8",
    accent_text="#ffffff",
    ok="#12855a",
    warn="#a86800",
    danger="#c62630",
    track_off="#cfd5de",
    knob="#ffffff",
    shadow="#d5d9e0",
)

THEMES = {"dark": DARK, "light": LIGHT}

# Ordered by preference; the first family the toolkit actually has wins.
UI_FONT_CANDIDATES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Inter",
    "Ubuntu",
    "Cantarell",
    "Noto Sans",
    "DejaVu Sans",
    "Helvetica",
]
MONO_FONT_CANDIDATES = [
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "Ubuntu Mono",
    "DejaVu Sans Mono",
    "Courier New",
]


def pick_font(root, candidates: list[str], fallback: str) -> str:
    from tkinter import font as tkfont

    available = {name.lower() for name in tkfont.families(root)}
    for candidate in candidates:
        if candidate.lower() in available:
            return candidate
    return fallback


class Fonts:
    def __init__(self, root) -> None:
        family = pick_font(root, UI_FONT_CANDIDATES, "TkDefaultFont")
        mono = pick_font(root, MONO_FONT_CANDIDATES, "TkFixedFont")
        self.family = family
        self.title = (family, 17, "bold")
        self.heading = (family, 11, "bold")
        self.body = (family, 10)
        self.small = (family, 9)
        self.tiny = (family, 8)
        self.metric = (family, 26, "bold")
        self.metric_unit = (family, 11)
        self.mono = (mono, 9)
