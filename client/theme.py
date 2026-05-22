"""Shared light-theme QSS used by both client and server UIs."""
from __future__ import annotations

LIGHT_QSS = """
QMainWindow { background-color:#ffffff; color:#0f172a; }
QWidget      { background-color:#ffffff; color:#0f172a; }
QTabWidget::pane { border:1px solid #e2e8f0; background-color:#ffffff; }
QTabBar::tab {
    background-color:#f1f5f9; color:#475569; padding:8px 16px;
    border-top-left-radius:6px; border-top-right-radius:6px;
    border:1px solid #e2e8f0; border-bottom:none;
}
QTabBar::tab:selected { background-color:#ffffff; color:#0f172a; }
QLabel, QGroupBox { color:#0f172a; }
QGroupBox {
    border:1px solid #e2e8f0; border-radius:8px; margin-top:10px;
    background-color:#f8fafc;
}
QGroupBox::title {
    subcontrol-origin:margin; left:10px; padding:0 4px;
    color:#1e293b; font-weight:bold;
}
QPushButton {
    background-color:#f1f5f9; color:#0f172a; border:1px solid #cbd5e1;
    padding:6px 14px; border-radius:6px;
}
QPushButton:hover    { background-color:#e2e8f0; border-color:#94a3b8; }
QPushButton:pressed  { background-color:#cbd5e1; }
QPushButton:disabled { background-color:#f8fafc; color:#94a3b8; border-color:#e2e8f0; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color:#ffffff; color:#0f172a; border:1px solid #cbd5e1;
    border-radius:6px; padding:4px;
    selection-background-color:#bfdbfe; selection-color:#0f172a;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border:1px solid #2563eb;
}
QListWidget, QTableWidget {
    background-color:#ffffff; color:#0f172a;
    border:1px solid #e2e8f0; border-radius:6px;
    gridline-color:#e2e8f0;
    selection-background-color:#dbeafe; selection-color:#0f172a;
    alternate-background-color:#f8fafc;
}
QHeaderView::section {
    background-color:#f1f5f9; color:#1e293b;
    padding:4px 8px; border:none; border-right:1px solid #e2e8f0;
    border-bottom:1px solid #e2e8f0;
}
QToolBar { background-color:#f8fafc; border-bottom:1px solid #e2e8f0; spacing:4px; padding:4px; }
QStatusBar { background-color:#f8fafc; color:#475569; border-top:1px solid #e2e8f0; }
QScrollBar:vertical {
    background:#f1f5f9; width:12px; margin:0; border:none;
}
QScrollBar::handle:vertical {
    background:#cbd5e1; border-radius:6px; min-height:20px;
}
QScrollBar::handle:vertical:hover { background:#94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QSplitter::handle { background-color:#e2e8f0; }
"""
