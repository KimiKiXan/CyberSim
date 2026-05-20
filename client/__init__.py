"""PyQt5 desktop client for CyberSim.

The ``main_window`` import is deferred so that ``client.api_client`` can be
used from non-Qt contexts (e.g. tests / scripts).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .main_window import MainWindow


def launch() -> None:
    from .main_window import launch as _launch
    _launch()


__all__ = ["MainWindow", "launch"]


def __getattr__(name: str):  # PEP 562 lazy attribute
    if name == "MainWindow":
        from .main_window import MainWindow
        return MainWindow
    raise AttributeError(name)
