"""Activity Monitor: live application log (persistent history arrives in Phase 7)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QLabel, QPlainTextEdit, QWidget

from app.paths import logs_dir
from app.ui.log_bridge import LogEntry, QtLogHandler
from app.ui.widgets.common import Page, hbox, make_button

_LEVELS = {"All": logging.DEBUG, "Info+": logging.INFO, "Warnings+": logging.WARNING, "Errors": logging.ERROR}


class ActivityPage(Page):
    def __init__(self, log_handler: QtLogHandler, parent: QWidget | None = None) -> None:
        super().__init__("Activity Monitor", "Live application log for this run.", parent)
        self._handler = log_handler
        self.level_combo = QComboBox()
        self.level_combo.addItems(list(_LEVELS))
        self.level_combo.setCurrentText("Info+")
        self.level_combo.currentTextChanged.connect(self._rebuild)
        self.clear_btn = make_button("Clear View")
        self.clear_btn.clicked.connect(lambda: self.view.clear())
        self.open_btn = make_button("Open Log Folder")
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        self.body.addLayout(hbox(QLabel("Show:"), self.level_combo, self.clear_btn, self.open_btn))
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.body.addWidget(self.view, 1)
        log_handler.emitter.record.connect(self._append)
        self._rebuild()

    def _threshold(self) -> int:
        return _LEVELS[self.level_combo.currentText()]

    def _rebuild(self, *_: object) -> None:
        self.view.clear()
        for entry in self._handler.entries:
            self._append(entry)

    @Slot(object)
    def _append(self, entry: LogEntry) -> None:
        if entry.levelno >= self._threshold():
            self.view.appendPlainText(f"{entry.timestamp:%Y-%m-%d %H:%M:%S}  {entry.level:<7} {entry.logger}: {entry.message}")
