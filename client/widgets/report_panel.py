"""Report panel — preview markdown report and export PDF/MD/JSON."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTextBrowser, QVBoxLayout, QWidget,
)


class ReportPanel(QWidget):
    build_requested = pyqtSignal(str, str)       # session_id, format
    download_requested = pyqtSignal(str, str, str)  # session_id, format, dest

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_id: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        self.title_lbl = QLabel("<b>Report Preview</b>  <span style='color:#9ca3af'>(no session loaded)</span>")
        header.addWidget(self.title_lbl)
        header.addStretch()
        self.fmt_select = QComboBox()
        self.fmt_select.addItems(["markdown", "pdf", "json"])
        header.addWidget(QLabel("Format:"))
        header.addWidget(self.fmt_select)
        header.addWidget(QPushButton("Build", clicked=self._emit_build))
        header.addWidget(QPushButton("Download…", clicked=self._emit_download))
        root.addLayout(header)

        self.preview = QTextBrowser(self)
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet(
            "QTextBrowser { background-color:#0b1020; color:#e5e7eb; "
            "border:1px solid #1f2937; border-radius:8px; padding:10px; }"
        )
        root.addWidget(self.preview, stretch=1)

    # ----------------------------------------------------------- public api
    def set_session(self, session_id: str | None, markdown: str | None) -> None:
        self._session_id = session_id
        if session_id:
            self.title_lbl.setText(f"<b>Report Preview</b>  <span style='color:#9ca3af'>(session {session_id})</span>")
        else:
            self.title_lbl.setText("<b>Report Preview</b>  <span style='color:#9ca3af'>(no session loaded)</span>")
        self.preview.setMarkdown(markdown or "_Build a report to preview it here._")

    # ------------------------------------------------------------- emits
    def _emit_build(self) -> None:
        if not self._session_id:
            QMessageBox.information(self, "No session", "Open a session before building a report.")
            return
        self.build_requested.emit(self._session_id, self.fmt_select.currentText())

    def _emit_download(self) -> None:
        if not self._session_id:
            QMessageBox.information(self, "No session", "Open a session before downloading a report.")
            return
        fmt = self.fmt_select.currentText()
        ext_map = {"markdown": ".md", "pdf": ".pdf", "json": ".json"}
        suggested = f"cybersim-{self._session_id}{ext_map.get(fmt, '.bin')}"
        path, _ = QFileDialog.getSaveFileName(self, "Save report as", suggested)
        if not path:
            return
        self.download_requested.emit(self._session_id, fmt, path)
