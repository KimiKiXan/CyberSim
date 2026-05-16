"""Helpers to run asyncio coroutines from PyQt6 widgets."""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, AsyncIterator, Callable, Coroutine, TypeVar

from PyQt6.QtCore import QObject, pyqtSignal

T = TypeVar("T")


class AsyncBridge(QObject):
    """Runs asyncio code on a dedicated thread; emits Qt signals back to the UI."""

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cybersim-async")
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


class StreamWorker(QObject):
    """Bridges an async-iterator into Qt signals."""

    item = pyqtSignal(object)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, bridge: AsyncBridge, factory: Callable[[], AsyncIterator[Any]]) -> None:
        super().__init__()
        self.bridge = bridge
        self.factory = factory
        self._future: Future | None = None
        self._cancelled = False

    def start(self) -> None:
        self._future = self.bridge.submit(self._consume())

    def cancel(self) -> None:
        self._cancelled = True
        if self._future:
            self._future.cancel()

    async def _consume(self) -> None:
        try:
            async for item in self.factory():
                if self._cancelled:
                    return
                self.item.emit(item)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
