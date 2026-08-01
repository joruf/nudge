"""Translation layer.

Language files are plain JSON in ``nudge/locales``. Adding a language means
dropping another file in there -- no code change. English is the fallback for
any key a translation happens to be missing, so a partial file is still
usable.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

DEFAULT_LANGUAGE = "en"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


class Translator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._language = DEFAULT_LANGUAGE
        self._catalog: dict[str, str] = {}
        self._fallback: dict[str, str] = self._read(DEFAULT_LANGUAGE)
        self._catalog = dict(self._fallback)

    # ------------------------------------------------------------- loading

    @staticmethod
    def _read(code: str) -> dict[str, str]:
        path = LOCALES_DIR / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str)}

    def available(self) -> list[tuple[str, str]]:
        """(code, display label) for every language file that parses."""
        found: list[tuple[str, str]] = []
        for path in sorted(LOCALES_DIR.glob("*.json")):
            code = path.stem
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            label = data.get("_label", code.upper())
            found.append((code, label))
        return found or [(DEFAULT_LANGUAGE, "English")]

    @property
    def language(self) -> str:
        with self._lock:
            return self._language

    def set_language(self, code: str) -> None:
        catalog = self._read(code)
        with self._lock:
            if not catalog and code != DEFAULT_LANGUAGE:
                return
            self._language = code
            self._catalog = catalog

    # --------------------------------------------------------- translation

    def get(self, key: str, **params) -> str:
        with self._lock:
            template = self._catalog.get(key) or self._fallback.get(key)
        if template is None:
            return key
        if not params:
            return template
        try:
            return template.format(**params)
        except (KeyError, IndexError, ValueError):
            # A malformed placeholder must not take the window down.
            return template


TRANSLATOR = Translator()


def t(key: str, **params) -> str:
    return TRANSLATOR.get(key, **params)


def set_language(code: str) -> None:
    TRANSLATOR.set_language(code)


def current_language() -> str:
    return TRANSLATOR.language


def available_languages() -> list[tuple[str, str]]:
    return TRANSLATOR.available()


class Msg:
    """A deferred translation.

    Techniques return these instead of finished strings, so a message logged
    in English still reads correctly after the user switches to German.
    """

    __slots__ = ("key", "params")

    def __init__(self, key: str, **params) -> None:
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return t(self.key, **self.params)

    def __repr__(self) -> str:
        return f"Msg({self.key!r}, {self.params!r})"
