"""Technique registry. Only the current platform's techniques are loaded."""

from __future__ import annotations

from ..paths import platform_key
from .base import PERIODIC, SUSTAINED, Availability, Technique, TechniqueError

__all__ = [
    "PERIODIC",
    "SUSTAINED",
    "Availability",
    "Technique",
    "TechniqueError",
    "load_techniques",
]


def load_techniques() -> list[Technique]:
    platform = platform_key()
    if platform == "windows":
        from . import windows_techniques

        return windows_techniques.build()
    if platform in ("linux", "macos"):
        from . import linux_techniques

        return linux_techniques.build()
    return []
