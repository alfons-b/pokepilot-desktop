"""Activity Monitor: live status, live log, session history and stored logs."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository
from app.monitoring.monitor import StatusMonitor, StatusSnapshot
from app.paths import logs_dir
from app.ui.log_bridge import LogEntry, QtLogHandler
from app.ui.pages.automation_page import format_duration
from app.ui.widgets.common import Page, hbox, make_button

_LEVELS = {"All": logging.DEBUG, "Info+": logging.INFO, "Warnings+": logging.WARNING, "Errors": logging.ERROR}
STATUS_FIELDS = [
    ("adb", "ADB connection"),
    ("emulator", "Emulator / device"),
    ("pgsharp", "PGSharp"),
    ("pokemon_go", "Pokémon GO"),
    ("scrcpy", "scrcpy"),
    ("profile", "Current profile"),
    ("session_state", "Session state"),
    ("current_action", "Current action"),
    ("duration", "Session duration"),
    ("last_verification", "Last UI verification"),
    ("last_error", "Last error"),
]
HISTORY_COLUMNS = ["Started", "Ended", "Profile", "Device", "Result", "Actions", "OK", "Unverified", "Failed",
                   "Last error"]


class ActivityPage(Page):
    def __init__(
        self,
        log_handler: QtLogHandler,
        monitor: StatusMonitor | None = None,
        history: SessionHistoryRepository | None = None,
        logs: ActivityLogRepository | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Activity Monitor", "Live status, logs and session history.", parent)
        self._handler = log_handler
        self._monitor = monitor
        self._history = history
        self._logs = logs

        status_box = QGroupBox("Live Status")
        grid = QGridLayout(status_box)
        grid.setHorizontalSpacing(18)
        self.status_labels: dict[str, QLabel] = {}
        for i, (key, title) in enumerate(STATUS_FIELDS):
            t = QLabel(f"{title}:")
            t.setObjectName("Muted")
            v = QLabel("-")
            v.setWordWrap(True)
            self.status_labels[key] = v
            grid.addWidget(t, i // 2, (i % 2) * 2)
            grid.addWidget(v, i // 2, (i % 2) * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.poll_btn = make_button("Check Apps Now", tooltip="Check PGSharp and Pokémon GO process state.")
        if monitor is not None:
            self.poll_btn.clicked.connect(monitor.poll_apps)
        else:
            self.poll_btn.setEnabled(False)
        note = QLabel("Counts shown here are PokePilot controller actions, not game statistics.")
        note.setObjectName("Muted")
        grid.addWidget(note, (len(STATUS_FIELDS) + 1) // 2, 0, 1, 3)
        grid.addWidget(self.poll_btn, (len(STATUS_FIELDS) + 1) // 2, 3)
        self.body.addWidget(status_box)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_live_tab(), "Live Log")
        self.tabs.addTab(self._build_history_tab(), "Session History")
        self.tabs.addTab(self._build_stored_tab(), "Stored Warnings && Errors")
        self.tabs.currentChanged.connect(self._on_tab)
        self.body.addWidget(self.tabs, 1)

        log_handler.emitter.record.connect(self._append)
        self._rebuild()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_duration)
        self._tick.start(1000)
        if monitor is not None:
            monitor.changed.connect(self._on_snapshot)
            self._on_snapshot(monitor.snapshot)

    # ------------------------------------------------------------------ tabs
    def _build_live_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.level_combo = QComboBox()
        self.level_combo.addItems(list(_LEVELS))
        self.level_combo.setCurrentText("Info+")
        self.level_combo.currentTextChanged.connect(self._rebuild)
        self.clear_btn = make_button("Clear View")
        self.clear_btn.clicked.connect(lambda: self.view.clear())
        self.open_btn = make_button("Open Log Folder")
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        lay.addLayout(hbox(QLabel("Show:"), self.level_combo, self.clear_btn, self.open_btn))
        lay.addWidget(self.view, 1)
        return w

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.history_table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history_table.setHorizontalHeaderLabels(HISTORY_COLUMNS)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.itemSelectionChanged.connect(self._show_session_log)
        self.session_log = QPlainTextEdit()
        self.session_log.setReadOnly(True)
        self.session_log.setMaximumHeight(180)
        self.history_refresh_btn = make_button("Refresh")
        self.history_refresh_btn.clicked.connect(self.refresh_history)
        lay.addLayout(hbox(self.history_refresh_btn))
        lay.addWidget(self.history_table, 1)
        lay.addWidget(QLabel("Log of the selected session:"))
        lay.addWidget(self.session_log)
        self._history_ids: list[int] = []
        return w

    def _build_stored_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.stored_level = QComboBox()
        self.stored_level.addItems(["WARNING", "ERROR", "INFO"])
        self.stored_level.currentTextChanged.connect(lambda _t: self.refresh_stored())
        self.stored_view = QPlainTextEdit()
        self.stored_view.setReadOnly(True)
        self.stored_refresh_btn = make_button("Refresh")
        self.stored_refresh_btn.clicked.connect(self.refresh_stored)
        lay.addLayout(hbox(QLabel("Minimum level:"), self.stored_level, self.stored_refresh_btn))
        lay.addWidget(self.stored_view, 1)
        return w

    def _on_tab(self, index: int) -> None:
        if index == 1:
            self.refresh_history()
        elif index == 2:
            self.refresh_stored()

    # --------------------------------------------------------------- history
    def refresh_history(self) -> None:
        if self._history is None:
            return
        records = self._history.recent(200)
        self._history_ids = [r.id for r in records]
        self.history_table.setRowCount(len(records))
        for row, r in enumerate(records):
            vals = [r.started_at.replace("T", " "), (r.ended_at or "-").replace("T", " "), r.profile_name,
                    r.device_serial, r.result, str(r.total), str(r.succeeded), str(r.unknown), str(r.failed),
                    r.last_error]
            for col, v in enumerate(vals):
                self.history_table.setItem(row, col, QTableWidgetItem(v))

    def _show_session_log(self) -> None:
        rows = self.history_table.selectionModel().selectedRows()
        if not rows or self._logs is None:
            return
        sid = self._history_ids[rows[0].row()]
        entries = reversed(self._logs.recent(1000, "DEBUG", session_id=sid))
        self.session_log.setPlainText(
            "\n".join(f"{e['timestamp'].replace('T', ' ')}  {e['level']:<7} {e['message']}" for e in entries)
        )

    def refresh_stored(self) -> None:
        if self._logs is None:
            return
        entries = self._logs.recent(1000, self.stored_level.currentText())
        self.stored_view.setPlainText(
            "\n".join(f"{e['timestamp'].replace('T', ' ')}  {e['level']:<7} {e['source']}: {e['message']}"
                      for e in entries)
        )

    # ---------------------------------------------------------------- status
    @Slot(object)
    def _on_snapshot(self, s: StatusSnapshot) -> None:
        for key, label in self.status_labels.items():
            if key != "duration":
                label.setText(str(getattr(s, key)))
        self._update_duration()

    def _update_duration(self) -> None:
        if self._monitor is not None:
            started = self._monitor.snapshot.session_started
            self.status_labels["duration"].setText(format_duration(started) if started else "-")

    # -------------------------------------------------------------- live log
    def _threshold(self) -> int:
        return _LEVELS[self.level_combo.currentText()]

    def _rebuild(self, *_: object) -> None:
        self.view.clear()
        for entry in self._handler.entries:
            self._append(entry)

    @Slot(object)
    def _append(self, entry: LogEntry) -> None:
        if entry.levelno >= self._threshold():
            self.view.appendPlainText(
                f"{entry.timestamp:%Y-%m-%d %H:%M:%S}  {entry.level:<7} {entry.logger}: {entry.message}"
            )
        if entry.levelno >= logging.ERROR and self._monitor is not None:
            self._monitor.note_error(entry.message)
