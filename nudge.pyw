"""Windows launcher. Double-click this file to start Nudge without a console.

The .pyw extension makes Windows use pythonw.exe, so no black window appears. Everything else is
nudge.py, which is deliberate: one launcher on both platforms means one behaviour on both
platforms, and the only difference here is the extension Windows needs to see.
"""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

runpy.run_module("nudge", run_name="__main__", alter_sys=True)
