"""Entry point for PyInstaller and for double-click launching: ``python pokepilot.py``."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
