"""Top-level PyQt5 control panel for the CyberSim server."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QAction, QApplication, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStatusBar, QToolBar, QVBoxLayout, QWidget,
)

from client.theme import LIGHT_QSS
from config.settings import CONFIG

from .controller import OllamaController, ServerProcessController


_LOG_COLORS = {
    "ERROR": "#b91c1c",
    "WARNING": "#b45309",
    "INFO": "#1d4ed8",
    "DEBUG": "#64748b",
    "controller": "#7c3aed",
    "ollama": "#0e7490",
}


class ServerControlWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CyberSim — Server Control")
        self._apply_adaptive_geometry()
        self.setStyleSheet(LIGHT_QSS)

        self.server = ServerProcessController(self)
        self.ollama = OllamaController(self)
        self._http_base = f"http://{CONFIG.server.host}:{CONFIG.server.port}"

        self._build_ui()
        self._wire()

        # periodic /health probe
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(4000)
        self._health_timer.timeout.connect(self._poll_health)
        self._health_timer.start()
        QTimer.singleShot(400, self._poll_health)

        # periodic /api/sessions probe
        self._sess_timer = QTimer(self)
        self._sess_timer.setInterval(6000)
        self._sess_timer.timeout.connect(self._poll_sessions)
        self._sess_timer.start()
        QTimer.singleShot(800, self._poll_sessions)

        # tool catalog refreshes only when the server is up
        QTimer.singleShot(1200, self._poll_tools)

    # ---------------------------------------------------- adaptive geometry
    def _apply_adaptive_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 760)
            return
        geo = screen.availableGeometry()
        w = max(1024, int(geo.width() * 0.75))
        h = max(680, int(geo.height() * 0.80))
        w = min(w, 1600)
        h = min(h, 1100)
        self.resize(w, h)
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        # -------- toolbar --------
        bar = QToolBar("Main")
        bar.setMovable(False)
        self.addToolBar(bar)
        self.act_start = QAction("Start Server", self, triggered=self._start_server)
        self.act_stop = QAction("Stop Server", self, triggered=self._stop_server)
        self.act_restart = QAction("Restart", self, triggered=self._restart_server)
        self.act_ollama = QAction("Start Ollama", self, triggered=self._start_ollama)
        self.act_open_reports = QAction("Open Reports Folder", self, triggered=self._open_reports)
        bar.addAction(self.act_start)
        bar.addAction(self.act_stop)
        bar.addAction(self.act_restart)
        bar.addSeparator()
        bar.addAction(self.act_ollama)
        bar.addSeparator()
        bar.addAction(self.act_open_reports)

        # -------- left side: status cards --------
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        left_l.setSpacing(8)

        # server card
        srv_box = QGroupBox("Server")
        srv_l = QVBoxLayout(srv_box)
        self.srv_state_lbl = QLabel("stopped")
        self.srv_state_lbl.setStyleSheet("color:#64748b; font-family: Consolas, monospace;")
        self.srv_endpoint_lbl = QLabel(
            f"endpoint: http://{CONFIG.server.host}:{CONFIG.server.port}"
        )
        self.srv_endpoint_lbl.setStyleSheet("color:#0f172a; font-family: Consolas, monospace;")
        srv_l.addWidget(self.srv_state_lbl)
        srv_l.addWidget(self.srv_endpoint_lbl)
        left_l.addWidget(srv_box)

        # ollama card
        oll_box = QGroupBox("Ollama")
        oll_l = QVBoxLayout(oll_box)
        self.oll_host_lbl = QLabel(f"host: {CONFIG.ollama.host}")
        self.oll_host_lbl.setStyleSheet("color:#0f172a; font-family: Consolas, monospace;")
        self.oll_status_lbl = QLabel("status: unknown")
        self.oll_status_lbl.setStyleSheet("color:#64748b; font-family: Consolas, monospace;")
        self.oll_models_lbl = QLabel("models: —")
        self.oll_models_lbl.setStyleSheet("color:#0f172a; font-family: Consolas, monospace;")
        self.oll_models_lbl.setWordWrap(True)
        oll_l.addWidget(self.oll_host_lbl)
        oll_l.addWidget(self.oll_status_lbl)
        oll_l.addWidget(self.oll_models_lbl)
        left_l.addWidget(oll_box)

        # tools card
        tools_box = QGroupBox("Tool Registry")
        tools_l = QVBoxLayout(tools_box)
        self.tools_list = QListWidget()
        tools_l.addWidget(self.tools_list, stretch=1)
        left_l.addWidget(tools_box, stretch=1)

        # sessions card
        sess_box = QGroupBox("Sessions")
        sess_l = QVBoxLayout(sess_box)
        self.sess_summary_lbl = QLabel("0 sessions")
        self.sess_summary_lbl.setStyleSheet("color:#0f172a; font-family: Consolas, monospace;")
        self.sess_list = QListWidget()
        self.sess_list.setMaximumHeight(140)
        sess_l.addWidget(self.sess_summary_lbl)
        sess_l.addWidget(self.sess_list, stretch=1)
        left_l.addWidget(sess_box)

        # -------- right side: live log --------
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 10)
        right_l.setSpacing(6)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("<b>Live Server Log</b>"))
        log_header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_log)
        log_header.addWidget(clear_btn)
        right_l.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.log_view.setFont(f)
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background-color:#f8fafc; color:#0f172a; "
            "border:1px solid #e2e8f0; border-radius:8px; padding:8px; }"
        )
        right_l.addWidget(self.log_view, stretch=1)

        # -------- splitter --------
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        total = max(self.width(), 1024)
        split.setSizes([int(total * 0.35), int(total * 0.65)])
        self.setCentralWidget(split)

        # -------- status bar --------
        sb = QStatusBar()
        sb.setStyleSheet("color:#475569;")
        sb.showMessage("idle")
        self.setStatusBar(sb)

        self._refresh_action_states()

    # ----------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.server.log.connect(self._append_log_chunk)
        self.server.state_changed.connect(self._on_server_state)
        self.ollama.log.connect(self._append_log_chunk)

    # -------------------------------------------------------- action handlers
    def _start_server(self) -> None:
        self._append_log("[ui] starting server ...\n", color=_LOG_COLORS["controller"])
        self.server.start()
        self._refresh_action_states()

    def _stop_server(self) -> None:
        self._append_log("[ui] stopping server ...\n", color=_LOG_COLORS["controller"])
        self.server.stop()
        self._refresh_action_states()

    def _restart_server(self) -> None:
        self._append_log("[ui] restarting server ...\n", color=_LOG_COLORS["controller"])
        self.server.restart()
        self._refresh_action_states()

    def _start_ollama(self) -> None:
        if not self.ollama.exe:
            QMessageBox.warning(
                self, "Ollama not found",
                "Could not locate ollama.exe in PATH or default install dirs.\n"
                "Install Ollama from https://ollama.com/download and retry.",
            )
            return
        if self.ollama.start_detached():
            self.statusBar().showMessage("Ollama: launched detached", 4000)

    def _open_reports(self) -> None:
        import subprocess
        path = CONFIG.paths.reports
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "CyberSim", f"Cannot open reports folder: {exc}")

    # ----------------------------------------------------- server-state cb
    def _on_server_state(self, state: str) -> None:
        colors = {
            "stopped":  "#64748b",
            "starting": "#b45309",
            "running":  "#15803d",
            "crashed":  "#b91c1c",
        }
        self.srv_state_lbl.setText(f"state: {state}")
        self.srv_state_lbl.setStyleSheet(
            f"color:{colors.get(state, '#64748b')}; "
            "font-family: Consolas, monospace; font-weight:bold;"
        )
        self.statusBar().showMessage(f"server: {state}", 4000)
        self._refresh_action_states()
        if state == "running":
            QTimer.singleShot(600, self._poll_health)
            QTimer.singleShot(900, self._poll_tools)

    def _refresh_action_states(self) -> None:
        running = self.server.is_running()
        self.act_start.setEnabled(not running)
        self.act_stop.setEnabled(running)
        self.act_restart.setEnabled(running)

    # ---------------------------------------------------------- health poll
    def _poll_health(self) -> None:
        try:
            with httpx.Client(timeout=3.0) as c:
                r = c.get(f"{self._http_base}/health")
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            self.oll_status_lbl.setText(f"status: server unreachable ({type(exc).__name__})")
            self.oll_status_lbl.setStyleSheet("color:#b91c1c; font-family: Consolas, monospace;")
            return
        ollama = data.get("ollama", {}) or {}
        ok = bool(ollama.get("ok"))
        host = ollama.get("host") or CONFIG.ollama.host
        models = ollama.get("available_models") or []
        self.oll_host_lbl.setText(f"host: {host}")
        self.oll_status_lbl.setText(
            f"status: {'OK' if ok else 'DOWN'} (model: {CONFIG.ollama.model})"
        )
        self.oll_status_lbl.setStyleSheet(
            f"color:{'#15803d' if ok else '#b91c1c'}; "
            "font-family: Consolas, monospace; font-weight:bold;"
        )
        self.oll_models_lbl.setText(
            "models: " + (", ".join(models) if models else "(none — auto-pull on first session)")
        )

    def _poll_sessions(self) -> None:
        try:
            with httpx.Client(timeout=3.0) as c:
                r = c.get(f"{self._http_base}/api/sessions")
                r.raise_for_status()
                items = r.json().get("sessions", []) or []
        except Exception:
            self.sess_summary_lbl.setText("0 sessions (server offline)")
            self.sess_list.clear()
            return
        self.sess_summary_lbl.setText(f"{len(items)} session(s)")
        self.sess_list.clear()
        for s in items[-30:]:
            sid = s.get("session_id", "?")[:8]
            state = s.get("state", "")
            iters = s.get("iterations", 0)
            obj = (s.get("objective") or "")[:60]
            self.sess_list.addItem(f"{sid}  [{state}]  iter={iters}  — {obj}")

    def _poll_tools(self) -> None:
        try:
            with httpx.Client(timeout=3.0) as c:
                r = c.get(f"{self._http_base}/api/tools")
                r.raise_for_status()
                payload = r.json()
        except Exception:
            self.tools_list.clear()
            self.tools_list.addItem("(server offline — tool registry unavailable)")
            return
        tools = payload.get("tools") if isinstance(payload, dict) else payload
        self.tools_list.clear()
        if not tools:
            self.tools_list.addItem("(no tools registered)")
            return
        for t in tools:
            name = t.get("name", "?")
            desc = (t.get("description") or "")[:80]
            self.tools_list.addItem(f"• {name}  —  {desc}")

    # --------------------------------------------------------- log helpers
    def _append_log_chunk(self, text: str) -> None:
        # Heuristic colour pick — match log level prefix or controller tag.
        color = "#0f172a"
        upper = text.upper()
        for level, c in _LOG_COLORS.items():
            tag = level.upper() if level not in {"controller", "ollama"} else f"[{level.upper()}]"
            if tag in upper:
                color = c
                break
        if text.lstrip().startswith("[controller]"):
            color = _LOG_COLORS["controller"]
        elif text.lstrip().startswith("[ollama]"):
            color = _LOG_COLORS["ollama"]
        self._append_log(text, color=color)

    def _append_log(self, text: str, *, color: str = "#0f172a") -> None:
        cur = self.log_view.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(text if text.endswith("\n") else text + "\n", fmt)
        self.log_view.setTextCursor(cur)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self) -> None:
        self.log_view.clear()

    # ----------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        if hasattr(self, "_health_timer"):
            self._health_timer.stop()
        if hasattr(self, "_sess_timer"):
            self._sess_timer.stop()
        if self.server.is_running():
            self.server.stop()
        super().closeEvent(event)


def launch() -> None:
    app = QApplication(sys.argv)
    try:
        import qdarktheme  # type: ignore
        qdarktheme.setup_theme("light")
    except Exception:
        pass
    win = ServerControlWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    launch()
