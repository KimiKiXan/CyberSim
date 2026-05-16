"""Operator dashboard — objective, target list, server health, uploads."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget,
)

from .targets_panel import TargetsPanel


class Dashboard(QWidget):
    launch_requested = pyqtSignal(str, list)
    upload_requested = pyqtSignal(list)
    refresh_health_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QGridLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- objective ----
        obj_box = QGroupBox("Attack Objective")
        obj_l = QVBoxLayout(obj_box)
        self.objective_edit = QTextEdit()
        self.objective_edit.setPlaceholderText(
            "Describe the scenario for the autonomous agent — e.g. "
            "'Map web stack on http://10.0.0.5, find injection points, validate SQLi, and report findings.'"
        )
        self.objective_edit.setMinimumHeight(120)
        obj_l.addWidget(self.objective_edit)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.launch_btn = QPushButton("▶ Launch ReAct Session")
        self.launch_btn.setStyleSheet(
            "QPushButton { background-color:#16a34a; color:white; padding:8px 18px; "
            "border-radius:6px; font-weight:bold; } "
            "QPushButton:hover { background-color:#15803d; }"
        )
        self.launch_btn.clicked.connect(self._emit_launch)
        bottom.addWidget(self.launch_btn)
        obj_l.addLayout(bottom)
        root.addWidget(obj_box, 0, 0)

        # ---- health card ----
        health_box = QGroupBox("Server / LLM Status")
        h_l = QVBoxLayout(health_box)
        self.health_lbl = QLabel("checking…")
        self.health_lbl.setWordWrap(True)
        self.health_lbl.setStyleSheet("color:#e5e7eb; font-family: Consolas, monospace;")
        h_l.addWidget(self.health_lbl)
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("Refresh", clicked=self.refresh_health_requested.emit))
        btn_row.addStretch()
        h_l.addLayout(btn_row)
        root.addWidget(health_box, 0, 1)

        # ---- targets ----
        self.targets_panel = TargetsPanel()
        root.addWidget(self.targets_panel, 1, 0)

        # ---- uploads ----
        up_box = QGroupBox("Scripts / Exploits / Wordlists")
        u_l = QVBoxLayout(up_box)
        u_l.addWidget(QLabel(
            "<span style='color:#9ca3af'>Upload custom payloads or wordlists. Files "
            "are stored under ./uploads/ on the server and can be referenced by tool "
            "arguments (e.g. wordlist=./uploads/custom.txt).</span>"
        ))
        self.uploads_list = QListWidget()
        self.uploads_list.setStyleSheet(
            "QListWidget { background-color:#0f172a; color:#e5e7eb; "
            "border:1px solid #1f2937; border-radius:6px; }"
        )
        u_l.addWidget(self.uploads_list, stretch=1)
        ub = QHBoxLayout()
        ub.addWidget(QPushButton("Upload…", clicked=self._pick_upload))
        ub.addStretch()
        u_l.addLayout(ub)
        root.addWidget(up_box, 1, 1)

        root.setColumnStretch(0, 3)
        root.setColumnStretch(1, 2)
        root.setRowStretch(1, 1)

    # ----------------------------------------------------------- callbacks
    def _emit_launch(self) -> None:
        objective = self.objective_edit.toPlainText().strip()
        targets = self.targets_panel.targets()
        self.launch_requested.emit(objective, targets)

    def _pick_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        if paths:
            self.upload_requested.emit(list(paths))

    # ----------------------------------------------------------- public api
    def set_health(self, text: str, ok: bool) -> None:
        self.health_lbl.setText(text)
        if ok:
            self.health_lbl.setStyleSheet("color:#34d399; font-family: Consolas, monospace;")
        else:
            self.health_lbl.setStyleSheet("color:#f87171; font-family: Consolas, monospace;")

    def set_uploads(self, items: list[dict]) -> None:
        self.uploads_list.clear()
        for it in items:
            self.uploads_list.addItem(f"{it.get('name')}   ({it.get('size')} bytes)")

    def set_busy(self, busy: bool) -> None:
        self.launch_btn.setEnabled(not busy)
        self.launch_btn.setText("… running" if busy else "▶ Launch ReAct Session")
