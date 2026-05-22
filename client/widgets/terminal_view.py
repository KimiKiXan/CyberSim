"""Real-time terminal view that consumes AgentEvent dictionaries."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QLabel


_COLOR_MAP = {
    "session_start": "#0e7490",  # cyan-700
    "session_end":   "#0e7490",
    "llm_thought":   "#7c3aed",  # violet-600
    "llm_raw":       "#64748b",  # slate-500
    "tool_call":     "#b45309",  # amber-700
    "tool_stream":   "#0f172a",  # slate-900
    "tool_result":   "#15803d",  # green-700
    "sandbox_block": "#c2410c",  # orange-700
    "agent_error":   "#b91c1c",  # red-700
    "final_answer":  "#1d4ed8",  # blue-700
    "metrics":       "#475569",  # slate-600
}


class TerminalView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>CyberSim Live Terminal</b>"))
        header.addStretch()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        header.addWidget(self.clear_btn)
        root.addLayout(header)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(20000)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.view.setFont(font)
        self.view.setStyleSheet(
            "QPlainTextEdit { background-color:#f8fafc; color:#0f172a; "
            "border:1px solid #e2e8f0; border-radius:8px; padding:8px; }"
        )
        root.addWidget(self.view, stretch=1)

        footer = QHBoxLayout()
        self.status_lbl = QLabel("idle")
        self.status_lbl.setStyleSheet("color:#475569;")
        footer.addWidget(self.status_lbl)
        footer.addStretch()
        root.addLayout(footer)

    # ---------------------------------------------------------------- public
    def clear(self) -> None:
        self.view.clear()

    def set_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    def append_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "?")
        payload = event.get("payload", {}) or {}
        ts = event.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
        except Exception:
            ts = ts[-8:]
        color = _COLOR_MAP.get(etype, "#0f172a")
        header = f"[{ts}] {etype.upper():<13}"
        body = self._format_payload(etype, payload)
        self._write(header + " ", color=color, bold=True)
        self._write(body + "\n", color=color)

    def append_raw(self, text: str, *, color: str = "#0f172a") -> None:
        self._write(text + "\n", color=color)

    # --------------------------------------------------------------- helpers
    def _format_payload(self, etype: str, payload: dict[str, Any]) -> str:
        if etype == "llm_thought":
            return payload.get("thought", "")
        if etype == "llm_raw":
            return f"[iter {payload.get('iteration')}] tokens={payload.get('completion_tokens')} latency={payload.get('latency_ms', 0):.0f}ms"
        if etype == "tool_call":
            return f"{payload.get('tool')}({payload.get('arguments')})"
        if etype == "tool_stream":
            stream = payload.get("stream", "stdout")
            return f"[{payload.get('tool')}:{stream}] {payload.get('line', '')}"
        if etype == "tool_result":
            return (
                f"{payload.get('tool')} → {payload.get('status')} in "
                f"{payload.get('duration_s', 0):.2f}s | {payload.get('summary', '')[:240]}"
            )
        if etype == "sandbox_block":
            return f"BLOCKED {payload.get('tool')} :: {payload.get('reason')}"
        if etype == "session_start":
            return f"objective='{payload.get('objective', '')[:120]}' targets={payload.get('targets')}"
        if etype == "session_end":
            return f"completed={payload.get('completed')} iterations={payload.get('iterations')}"
        if etype == "metrics":
            return ", ".join(f"{k}={v}" for k, v in payload.items())
        if etype == "final_answer":
            return f"REPORT:\n{payload.get('report', '')}"
        if etype == "agent_error":
            return f"ERROR: {payload.get('error')}"
        return str(payload)

    def _write(self, text: str, *, color: str = "#0f172a", bold: bool = False) -> None:
        cur = self.view.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        font = self.view.font()
        font.setBold(bold)
        fmt.setFont(font)
        cur.insertText(text, fmt)
        self.view.setTextCursor(cur)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())
