#!/usr/bin/env python3
"""Root launcher so `python3 autoplay.py` works without installing the package."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roblox_autoplay.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
