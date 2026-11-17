"""Application stylesheet and status colours."""

from __future__ import annotations

from app.paths import assets_dir

STATUS_COLORS: dict[str, str] = {
    "ok": "#1f9d55",
    "warn": "#d97706",
    "error": "#dc2626",
    "info": "#2563eb",
    "idle": "#9ca3af",
}

_STYLESHEET_TEMPLATE = """
QMainWindow, QWidget#Page { background: #f4f5f7; }
QWidget { font-size: 10pt; color: #1f2937; }

QListWidget#Sidebar {
    background: #1e2330; border: none; padding: 12px 8px; outline: 0;
}
QListWidget#Sidebar::item {
    color: #cbd2e1; padding: 10px 14px; border-radius: 6px; margin: 2px 0;
}
QListWidget#Sidebar::item:hover { background: #2a3142; }
QListWidget#Sidebar::item:selected { background: #3b82f6; color: white; }
QLabel#SidebarTitle {
    background: #1e2330; color: white; font-size: 14pt; font-weight: 600; padding: 18px 20px 6px 20px;
}
QLabel#SidebarVersion { background: #1e2330; color: #7c869c; padding: 0 20px 10px 20px; font-size: 9pt; }

QLabel#PageTitle { font-size: 17pt; font-weight: 600; color: #111827; }
QLabel#PageSubtitle { color: #6b7280; }
QLabel#Muted { color: #6b7280; }
QLabel#CardTitle { color: #6b7280; font-size: 9pt; font-weight: 600; text-transform: uppercase; }
QLabel#CardDetail { color: #4b5563; font-size: 9pt; }

QFrame#Card, QGroupBox {
    background: white; border: 1px solid #e5e7eb; border-radius: 10px;
}
QGroupBox { margin-top: 14px; padding: 14px 12px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #374151; }

QPushButton {
    background: white; border: 1px solid #d1d5db; border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { background: #f3f4f6; }
QPushButton:pressed { background: #e5e7eb; }
QPushButton:disabled { color: #9ca3af; background: #f9fafb; border-color: #e5e7eb; }
QPushButton[variant="primary"] { background: #3b82f6; color: white; border-color: #3b82f6; }
QPushButton[variant="primary"]:hover { background: #2563eb; }
QPushButton[variant="primary"]:disabled { background: #93c5fd; border-color: #93c5fd; color: #eff6ff; }
QPushButton[variant="danger"] { background: #dc2626; color: white; border-color: #dc2626; font-weight: 600; }
QPushButton[variant="danger"]:disabled { background: #fca5a5; border-color: #fca5a5; color: #fef2f2; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: white; border: 1px solid #d1d5db; border-radius: 6px; padding: 5px 8px;
}
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 20px; border-left: 1px solid #e5e7eb; background: #f9fafb;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 6px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 6px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@ICONS@/arrow-up.svg); width: 10px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QComboBox::down-arrow {
    image: url(@ICONS@/arrow-down.svg); width: 10px; height: 6px;
}
QComboBox { padding-right: 24px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #3b82f6; }

QTableWidget, QListWidget#LogList, QPlainTextEdit {
    background: white; border: 1px solid #e5e7eb; border-radius: 8px; gridline-color: #f0f1f3;
}
QHeaderView::section {
    background: #f9fafb; border: none; border-bottom: 1px solid #e5e7eb; padding: 6px; font-weight: 600;
}
QTableWidget::item:selected { background: #dbeafe; color: #111827; }

QLabel#Banner { border-radius: 6px; padding: 8px 12px; }
QLabel#Banner[level="ok"] { background: #dcfce7; color: #166534; }
QLabel#Banner[level="error"] { background: #fee2e2; color: #991b1b; }
QLabel#Banner[level="info"] { background: #dbeafe; color: #1e40af; }
QLabel#Banner[level="warn"] { background: #fef3c7; color: #92400e; }
QStatusBar { background: white; border-top: 1px solid #e5e7eb; }
"""


def build_stylesheet() -> str:
    """Return the stylesheet with icon paths resolved (works when frozen too)."""
    icons = (assets_dir() / "icons").as_posix()
    return _STYLESHEET_TEMPLATE.replace("@ICONS@", icons)
