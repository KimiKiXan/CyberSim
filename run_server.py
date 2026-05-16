"""Entry point — launches the CyberSim FastAPI/WebSocket backend."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# allow running this file from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.app import run_server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    run_server()


if __name__ == "__main__":
    main()
