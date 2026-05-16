"""Entry point — launches the PyQt6 desktop client."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client.main_window import launch


if __name__ == "__main__":
    launch()
