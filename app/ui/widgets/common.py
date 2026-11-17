"""Small reusable widgets: status badge, status card, banner, page scaffold."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import STATUS_COLORS


class StatusBadge(QLabel):
    """Coloured dot + text. ``level`` is one of ok / warn / error / info / idle."""

    def __init__(self, text: str = "Unknown", level: str = "idle", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.level = level
        self.text_value = text
        self.set_status(level, text)

    def set_status(self, level: str, text: str) -> None:
        self.level = level
        self.text_value = text
        color = STATUS_COLORS.get(level, STATUS_COLORS["idle"])
        safe = text.replace("&", "&amp;").replace("<", "&lt;")
        self.setText(f'<span style="color:{color}; font-size:13pt;">&#9679;</span>&nbsp;<b>{safe}</b>')


class StatusCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title.upper())
        title_label.setObjectName("CardTitle")
        self.badge = StatusBadge()
        self.detail = QLabel("")
        self.detail.setObjectName("CardDetail")
        self.detail.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(self.badge)
        layout.addWidget(self.detail)
        layout.addStretch(1)

    def set_status(self, level: str, text: str, detail: str = "") -> None:
        self.badge.set_status(level, text)
        self.detail.setText(detail)


class Banner(QLabel):
    """Inline, non-modal message area. Auto-hides success/info messages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, level: str, text: str, timeout_ms: int | None = None) -> None:
        self.setProperty("level", level)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.show()
        if timeout_ms is None:
            timeout_ms = 0 if level in ("error", "warn") else 6000
        if timeout_ms:
            self._timer.start(timeout_ms)
        else:
            self._timer.stop()


def make_button(text: str, variant: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class Page(QWidget):
    """Standard page scaffold with a title, subtitle and a content layout."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(14)
        header = QVBoxLayout()
        header.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        header.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("PageSubtitle")
            s.setWordWrap(True)
            header.addWidget(s)
        outer.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        outer.addLayout(self.body, 1)


def hbox(*widgets: QWidget, stretch_end: bool = True, spacing: int = 8) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for w in widgets:
        row.addWidget(w)
    if stretch_end:
        row.addStretch(1)
    return row
