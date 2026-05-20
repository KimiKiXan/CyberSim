"""Authorized-targets panel — supports manual entry plus JSON/CSV import."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QVBoxLayout, QWidget, QMessageBox,
)


class TargetsPanel(QWidget):
    targets_changed = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel("<b>Authorized Targets (Sandbox Allow-list)</b>"))
        root.addWidget(QLabel(
            "<span style='color:#9ca3af'>Only hosts/IPs/CIDRs listed here may be "
            "touched by tools. Entries can be IPs (10.0.0.5), CIDRs (10.0.0.0/24), "
            "URLs (http://target/), or hostnames (lab.local).</span>"
        ))

        entry_row = QHBoxLayout()
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("add target… (e.g. 10.0.0.5 or http://lab.local)")
        self.input.returnPressed.connect(self.add_target_from_input)
        entry_row.addWidget(self.input, stretch=1)
        add_btn = QPushButton("Add", clicked=self.add_target_from_input)
        entry_row.addWidget(add_btn)
        root.addLayout(entry_row)

        self.list = QListWidget(self)
        self.list.setStyleSheet(
            "QListWidget { background-color:#0f172a; color:#e5e7eb; "
            "border:1px solid #1f2937; border-radius:6px; }"
        )
        root.addWidget(self.list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("Remove Selected", clicked=self.remove_selected))
        btn_row.addWidget(QPushButton("Import JSON/CSV…", clicked=self.import_file))
        btn_row.addWidget(QPushButton("Export…", clicked=self.export_file))
        btn_row.addStretch()
        btn_row.addWidget(QPushButton("Clear", clicked=self.clear))
        root.addLayout(btn_row)

    # -------------------------------------------------------------- mutations
    def targets(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def add_target(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            return
        existing = self.targets()
        if value in existing:
            return
        self.list.addItem(value)
        self.targets_changed.emit(self.targets())

    def add_target_from_input(self) -> None:
        self.add_target(self.input.text())
        self.input.clear()

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.targets_changed.emit(self.targets())

    def clear(self) -> None:
        self.list.clear()
        self.targets_changed.emit([])

    # --------------------------------------------------------------- import
    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import targets", "", "Targets (*.json *.csv *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            entries = _parse_targets_file(Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        for e in entries:
            self.add_target(e)

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export targets", "targets.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        targets = self.targets()
        if path.lower().endswith(".csv"):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["target"])
                for t in targets:
                    w.writerow([t])
        else:
            Path(path).write_text(json.dumps({"targets": targets}, indent=2), encoding="utf-8")


def _parse_targets_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict):
            for key in ("targets", "hosts", "ips"):
                if key in data and isinstance(data[key], list):
                    return [str(x) for x in data[key]]
        raise ValueError("JSON must be a list or contain a 'targets' list")
    if path.suffix.lower() == ".csv":
        out: list[str] = []
        reader = csv.reader(io.StringIO(text))
        for i, row in enumerate(reader):
            if not row:
                continue
            if i == 0 and row[0].strip().lower() in {"target", "host", "ip"}:
                continue
            out.append(row[0].strip())
        return out
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
