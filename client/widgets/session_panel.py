"""Session history panel — lists previous attack sessions on the server."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class SessionPanel(QWidget):
    refresh_requested = pyqtSignal()
    open_session = pyqtSignal(str)
    stop_session = pyqtSignal(str)
    open_report = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Sessions</b>"))
        header.addStretch()
        header.addWidget(QPushButton("Refresh", clicked=self.refresh_requested.emit))
        root.addLayout(header)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["ID", "State", "Objective", "Targets", "Iter."])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget { background-color:#0f172a; color:#e5e7eb; gridline-color:#1f2937;"
            " border:1px solid #1f2937; border-radius:6px; }"
        )
        root.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        actions.addWidget(QPushButton("Open Terminal", clicked=self._emit_open))
        actions.addWidget(QPushButton("Build Report", clicked=self._emit_report))
        actions.addStretch()
        actions.addWidget(QPushButton("Stop Selected", clicked=self._emit_stop))
        root.addLayout(actions)

    def _selected_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _emit_open(self) -> None:
        sid = self._selected_id()
        if sid:
            self.open_session.emit(sid)

    def _emit_stop(self) -> None:
        sid = self._selected_id()
        if sid:
            self.stop_session.emit(sid)

    def _emit_report(self) -> None:
        sid = self._selected_id()
        if sid:
            self.open_report.emit(sid)

    def set_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self.table.setRowCount(0)
        for s in sessions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(s.get("session_id", "")))
            state_item = QTableWidgetItem(s.get("state", ""))
            state_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, state_item)
            self.table.setItem(row, 2, QTableWidgetItem(s.get("objective", "")))
            self.table.setItem(row, 3, QTableWidgetItem(", ".join(s.get("targets", []))))
            self.table.setItem(row, 4, QTableWidgetItem(str(s.get("iterations", 0))))
