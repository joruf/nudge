#!/usr/bin/env python3
"""Launcher. Start Nudge without knowing where it lives:

    python3 nudge.py
    python3 nudge.py --list

Arguments are passed straight through. `python3 -m nudge` does the same thing from inside the
directory; this file is what a desktop entry, a file manager double-click or a shortcut can point
at, because it works from any working directory.

`runpy` rather than importing and calling `main()`: the package's `__main__` checks for missing
system packages before it imports anything that needs them, and that check is guarded by
`__name__ == "__main__"`. Running the module under that name is what keeps a launcher identical to
the command line -- including the window that installs what is missing.
"""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

runpy.run_module("nudge", run_name="__main__", alter_sys=True)
