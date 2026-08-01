"""Windows launcher. Double-click this file to start Nudge without a console.

The .pyw extension makes Windows use pythonw.exe, so no black window appears.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nudge.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
