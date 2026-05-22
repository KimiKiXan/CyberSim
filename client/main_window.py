"""Top-level CyberSim PyQt5 window."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction, QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSplitter, QStatusBar, QTabWidget, QToolBar, QVBoxLayout,
    QWidget,
)

from .api_client import CyberSimClient, ServerEndpoint
from .async_runner import AsyncBridge, StreamWorker
from .theme import LIGHT_QSS
from .widgets import Dashboard, ReportPanel, SessionPanel, TerminalView


class MainWindow(QMainWindow):
    def __init__(self, endpoint: ServerEndpoint | None = None) -> None:
        super().__init__()
        self.setWindowTitle("CyberSim — Autonomous LLM Cyberattack Simulator")
        self._apply_adaptive_geometry()
        self.client = CyberSimClient(endpoint)
        self.bridge = AsyncBridge()
        self._stream_worker: StreamWorker | None = None
        self._current_session: str | None = None

        self._build_ui()
        self._wire_signals()
        QTimer.singleShot(150, self.refresh_health)
        QTimer.singleShot(250, self.refresh_uploads)
        QTimer.singleShot(350, self.refresh_sessions)

        # Periodically re-probe /health so the status card recovers when the
        # server is (re)started while the client is already running.
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5000)   # 5 s
        self._health_timer.timeout.connect(self.refresh_health)
        self._health_timer.start()

    # ---------------------------------------------------- adaptive geometry
    def _apply_adaptive_geometry(self) -> None:
        """Size the window relative to the current screen, keeping a reasonable floor."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        geo = screen.availableGeometry()
        w = max(1024, int(geo.width() * 0.85))
        h = max(700, int(geo.height() * 0.85))
        # Cap so very-large monitors don't open a 4K window by default.
        w = min(w, 1920)
        h = min(h, 1200)
        self.resize(w, h)
        # Center on the active screen.
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.setStyleSheet(LIGHT_QSS)
        self.dashboard = Dashboard()
        self.terminal = TerminalView()
        self.session_panel = SessionPanel()
        self.report_panel = ReportPanel()

        # left = dashboard, right tabs = terminal / sessions / reports
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.dashboard)
        right_tabs = QTabWidget()
        right_tabs.addTab(self.terminal, "Live Terminal")
        right_tabs.addTab(self.session_panel, "Sessions")
        right_tabs.addTab(self.report_panel, "Report")
        splitter.addWidget(right_tabs)
        # Relative split — left dashboard ~37%, right tabs ~63%.
        total = max(self.width(), 1024)
        splitter.setSizes([int(total * 0.37), int(total * 0.63)])
        self.setCentralWidget(splitter)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(QAction("Refresh Health", self, triggered=self.refresh_health))
        toolbar.addAction(QAction("Refresh Sessions", self, triggered=self.refresh_sessions))
        toolbar.addAction(QAction("Open Reports Folder", self, triggered=self._open_reports_folder))

        sb = QStatusBar()
        sb.setStyleSheet("color:#475569;")
        sb.showMessage(f"Endpoint: {self.client.endpoint.http_base}")
        self.setStatusBar(sb)

    def _wire_signals(self) -> None:
        self.dashboard.launch_requested.connect(self.launch_session)
        self.dashboard.upload_requested.connect(self.upload_files)
        self.dashboard.refresh_health_requested.connect(self.refresh_health)
        self.session_panel.refresh_requested.connect(self.refresh_sessions)
        self.session_panel.open_session.connect(self.open_session)
        self.session_panel.stop_session.connect(self.stop_session)
        self.session_panel.open_report.connect(self.open_session)
        self.report_panel.build_requested.connect(self.build_report)
        self.report_panel.download_requested.connect(self.download_report)

    # ---------------------------------------------------------- async helpers
    def _run(self, coro, on_ok=None, on_err=None) -> None:
        fut = self.bridge.submit(coro)

        def _cb(_fut) -> None:
            try:
                result = _fut.result()
            except Exception as exc:  # noqa: BLE001
                if on_err:
                    QTimer.singleShot(0, lambda: on_err(exc))
                else:
                    QTimer.singleShot(0, lambda: self._error(f"{type(exc).__name__}: {exc}"))
                return
            if on_ok:
                QTimer.singleShot(0, lambda: on_ok(result))

        fut.add_done_callback(_cb)

    def _error(self, message: str) -> None:
        QMessageBox.critical(self, "CyberSim", message)
        self.statusBar().showMessage(message, 8000)

    # ---------------------------------------------------------- health probe
    def refresh_health(self) -> None:
        self.dashboard.set_health("checking…", True)

        def ok(data):
            ollama = data.get("ollama", {})
            available = ollama.get("available_models", []) or []
            healthy = ollama.get("ok", False)
            text = (
                f"server: OK\nollama: {'OK' if healthy else 'DOWN'} @ {ollama.get('host')}\n"
                f"models: {', '.join(available) or '(none — auto-pull on first session)'}"
            )
            self.dashboard.set_health(text, healthy)

        def err(exc):
            self.dashboard.set_health(f"server unreachable\n{exc}", False)

        self._run(self.client.health(), on_ok=ok, on_err=err)

    # ----------------------------------------------------------- uploads
    def refresh_uploads(self) -> None:
        async def fetch():
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{self.client.endpoint.http_base}/api/uploads")
                r.raise_for_status()
                return r.json().get("uploads", [])

        def ok(items):
            self.dashboard.set_uploads(items)

        def err(_exc):
            pass

        self._run(fetch(), on_ok=ok, on_err=err)

    def upload_files(self, paths: list[str]) -> None:
        async def go():
            results = []
            for p in paths:
                results.append(await self.client.upload_file(p))
            return results

        def ok(results):
            self.statusBar().showMessage(f"Uploaded {len(results)} file(s)", 4000)
            self.refresh_uploads()

        self._run(go(), on_ok=ok)

    # ---------------------------------------------------------- session launch
    def launch_session(self, objective: str, targets: list[str]) -> None:
        if not objective:
            self._error("Provide an objective for the agent.")
            return
        if not targets:
            self._error("Add at least one authorized target before launching.")
            return
        self.dashboard.set_busy(True)
        self.terminal.clear()
        self.terminal.set_status("launching session…")

        def ok(data):
            sid = data.get("session_id")
            self.statusBar().showMessage(f"Session {sid} started", 4000)
            self.refresh_sessions()
            self.open_session(sid)

        def err(exc):
            self.dashboard.set_busy(False)
            self._error(str(exc))

        self._run(self.client.start_session(objective, targets), on_ok=ok, on_err=err)

    # ---------------------------------------------------------- session stream
    def open_session(self, session_id: str) -> None:
        if self._stream_worker is not None:
            self._stream_worker.cancel()
            self._stream_worker = None
        self._current_session = session_id
        self.terminal.clear()
        self.terminal.set_status(f"streaming {session_id}…")
        self.report_panel.set_session(session_id, "_session running — build the report once it finishes._")

        def factory():
            return self.client.stream_session(session_id)

        worker = StreamWorker(self.bridge, factory)
        worker.item.connect(self._on_event)
        worker.finished.connect(self._on_stream_done)
        worker.error.connect(lambda msg: self.terminal.append_raw(msg, color="#b91c1c"))
        worker.start()
        self._stream_worker = worker

    @pyqtSlot(object)
    def _on_event(self, ev: object) -> None:
        if not isinstance(ev, dict):
            return
        self.terminal.append_event(ev)
        if ev.get("type") == "session_end":
            self.dashboard.set_busy(False)
            self.refresh_sessions()
            if self._current_session:
                self._build_preview(self._current_session)

    @pyqtSlot()
    def _on_stream_done(self) -> None:
        self.terminal.set_status("stream closed")

    # ----------------------------------------------------------- sessions
    def refresh_sessions(self) -> None:
        def ok(items):
            self.session_panel.set_sessions(items)

        self._run(self.client.list_sessions(), on_ok=ok)

    def stop_session(self, session_id: str) -> None:
        def ok(_):
            self.statusBar().showMessage(f"Stopped {session_id}", 4000)
            self.refresh_sessions()

        self._run(self.client.stop_session(session_id), on_ok=ok)

    # ----------------------------------------------------------- reports
    def _build_preview(self, session_id: str) -> None:
        async def go():
            await self.client.build_report(session_id, "markdown")
            data = await self.client.fetch_session(session_id)
            return data

        def ok(data):
            from server.report_generator import ReportData, ReportGenerator
            try:
                rd = ReportData(**data)
                md = ReportGenerator().render_markdown(rd)
            except Exception as exc:  # noqa: BLE001
                md = f"_Preview unavailable: {exc}_"
            self.report_panel.set_session(session_id, md)

        self._run(go(), on_ok=ok)

    def build_report(self, session_id: str, fmt: str) -> None:
        def ok(data):
            self.statusBar().showMessage(f"Report built: {data.get('path')}", 6000)
            self._build_preview(session_id)

        self._run(self.client.build_report(session_id, fmt), on_ok=ok)

    def download_report(self, session_id: str, fmt: str, dest: str) -> None:
        def ok(path):
            self.statusBar().showMessage(f"Downloaded report to {path}", 6000)

        self._run(self.client.download_report(session_id, fmt, dest), on_ok=ok)

    def _open_reports_folder(self) -> None:
        import os, subprocess
        from config.settings import CONFIG
        path = CONFIG.paths.reports
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            self._error(f"Cannot open reports folder: {exc}")

    # ----------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        if hasattr(self, "_health_timer"):
            self._health_timer.stop()
        if self._stream_worker:
            self._stream_worker.cancel()
        self.bridge.stop()
        super().closeEvent(event)


def launch() -> None:
    app = QApplication(sys.argv)
    try:
        import qdarktheme  # type: ignore
        qdarktheme.setup_theme("light")
    except Exception:
        pass
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    launch()
