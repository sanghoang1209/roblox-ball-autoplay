#!/usr/bin/env python3
"""Root launcher for the Roblox Ball Autoplay Web UI (`python3 app.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roblox_autoplay.ui.web_app import main  # noqa: E402

if __name__ == "__main__":
    main()
