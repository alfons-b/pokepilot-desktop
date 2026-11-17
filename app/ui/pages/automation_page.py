"""Automation Manager: profiles, ordered actions, and session control."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.automation.engine import SessionSummary
from app.automation.models import Action, ActionStatus, Profile, validate_profile
from app.automation.repository import ProfileError
from app.automation.session_manager import SessionManager
from app.automation.state_machine import ACTIVE, SessionState
from app.pgsharp.controller import PgsharpController
from app.ui.theme import STATUS_COLORS
from app.ui.widgets.action_dialog import ActionDialog
from app.ui.widgets.common import Banner, Page, StatusBadge, hbox, make_button

STATUS_LEVEL = {
    ActionStatus.PENDING: "idle", ActionStatus.RUNNING: "info", ActionStatus.SUCCEEDED: "ok",
    ActionStatus.FAILED: "error", ActionStatus.UNKNOWN: "warn", ActionStatus.SKIPPED: "idle",
    ActionStatus.CANCELLED: "idle",
}
STATE_LEVEL = {
    SessionState.IDLE: "idle", SessionState.PREPARING: "info", SessionState.RUNNING: "ok",
    SessionState.PAUSED: "warn", SessionState.STOPPING: "warn", SessionState.COMPLETED: "ok",
    SessionState.FAILED: "error",
}
COLUMNS = ["#", "Type", "Parameters", "Timeout", "Expected state", "On error", "Status"]


def format_duration(start: datetime | None) -> str:
    if start is None:
        return "-"
    secs = int((datetime.now() - start).total_seconds())
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


class AutomationPage(Page):
    def __init__(self, sessions: SessionManager, pg: PgsharpController, parent: QWidget | None = None) -> None:
        super().__init__("Automation Manager", "Build profiles of ordered UI actions and run them as a session.", parent)
        self._sessions = sessions
        self._pg = pg
        self._repo = sessions.profiles
        self._profile: Profile | None = None
        self._running_profile_id: int | None = None
        self.banner = Banner()
        self.body.addWidget(self.banner)

        row = QHBoxLayout()
        row.setSpacing(14)

        # Profiles
        prof_box = QGroupBox("Profiles")
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(lambda *_: self._on_profile_selected())
        self.new_btn = make_button("New")
        self.rename_btn = make_button("Rename")
        self.dup_btn = make_button("Duplicate")
        self.delete_btn = make_button("Delete")
        self.import_btn = make_button("Import...")
        self.export_btn = make_button("Export...")
        self.new_btn.clicked.connect(self._new_profile)
        self.rename_btn.clicked.connect(self._rename_profile)
        self.dup_btn.clicked.connect(self._duplicate_profile)
        self.delete_btn.clicked.connect(self._delete_profile)
        self.import_btn.clicked.connect(self._import_profile)
        self.export_btn.clicked.connect(self._export_profile)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Description")
        self.desc_edit.editingFinished.connect(self._save_description)
        pl = QVBoxLayout(prof_box)
        pl.addWidget(self.profile_list, 1)
        pl.addWidget(self.desc_edit)
        pl.addLayout(hbox(self.new_btn, self.rename_btn, self.dup_btn))
        pl.addLayout(hbox(self.delete_btn, self.import_btn, self.export_btn))
        prof_box.setMaximumWidth(330)
        row.addWidget(prof_box)

        # Actions
        act_box = QGroupBox("Actions")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _i: self._edit_action())
        self.add_btn = make_button("Add", "primary")
        self.edit_btn = make_button("Edit")
        self.remove_btn = make_button("Remove")
        self.up_btn = make_button("Move Up")
        self.down_btn = make_button("Move Down")
        self.add_btn.clicked.connect(self._add_action)
        self.edit_btn.clicked.connect(self._edit_action)
        self.remove_btn.clicked.connect(self._remove_action)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setObjectName("Muted")
        al = QVBoxLayout(act_box)
        al.addWidget(self.table, 1)
        al.addLayout(hbox(self.add_btn, self.edit_btn, self.remove_btn, self.up_btn, self.down_btn))
        al.addWidget(self.validation_label)
        row.addWidget(act_box, 1)
        self.body.addLayout(row, 3)

        # Session
        sess_box = QGroupBox("Session")
        self.state_badge = StatusBadge("IDLE", "idle")
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.start_btn = make_button("Start", "primary")
        self.pause_btn = make_button("Pause")
        self.resume_btn = make_button("Resume")
        self.stop_btn = make_button("Stop", tooltip="Finish the current action, then stop.")
        self.emergency_btn = make_button("Emergency Stop", "danger", "Interrupt immediately.")
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(sessions.pause)
        self.resume_btn.clicked.connect(sessions.resume)
        self.stop_btn.clicked.connect(sessions.stop)
        self.emergency_btn.clicked.connect(sessions.emergency_stop)
        self.log_list = QListWidget()
        self.log_list.setObjectName("LogList")
        sl = QVBoxLayout(sess_box)
        sl.addLayout(hbox(self.state_badge, self.start_btn, self.pause_btn, self.resume_btn, self.stop_btn,
                          self.emergency_btn))
        sl.addWidget(self.info_label)
        sl.addWidget(self.log_list, 1)
        self.body.addWidget(sess_box, 2)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_info)
        self._timer.start(1000)

        sessions.state_changed.connect(self._on_state)
        sessions.action_updated.connect(self._on_action_updated)
        sessions.session_log.connect(self._on_log)
        sessions.session_finished.connect(self._on_finished)
        sessions.session_started.connect(self._on_started)
        sessions.operation_failed.connect(lambda op, m: self.banner.show_message("error", f"{op}: {m}"))
        pg.layout_changed.connect(self._refresh_validation)
        self.reload_profiles(sessions.current_profile_id)
        self._on_state(SessionState.IDLE)

    # ----------------------------------------------------------- profiles
    def reload_profiles(self, select_id: int | None = None) -> None:
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for pid, name, count in self._repo.list():
            item = QListWidgetItem(f"{name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.profile_list.addItem(item)
            if pid == select_id:
                self.profile_list.setCurrentItem(item)
        self.profile_list.blockSignals(False)
        self._on_profile_selected()

    def _selected_id(self) -> int | None:
        item = self.profile_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_profile_selected(self) -> None:
        pid = self._selected_id()
        self._profile = None
        if pid is not None:
            try:
                self._profile = self._repo.get(pid)
            except ProfileError as exc:
                self.banner.show_message("error", str(exc))
            if not self._sessions.is_active:
                self._sessions.set_current_profile(pid)
        self.desc_edit.setText(self._profile.description if self._profile else "")
        self._render_actions()
        self._update_buttons()

    def _locked(self) -> bool:
        """Editing the running profile is not allowed."""
        if self._sessions.is_active and self._profile and self._profile.id == self._running_profile_id:
            self.banner.show_message("warn", "Stop the session before editing the running profile.")
            return True
        return False

    def _persist(self) -> bool:
        if self._profile is None:
            return False
        try:
            self._repo.save(self._profile)
        except ProfileError as exc:
            self.banner.show_message("error", str(exc))
            return False
        self._render_actions()
        self._refresh_list_labels()
        return True

    def _refresh_list_labels(self) -> None:
        counts = {pid: (name, n) for pid, name, n in self._repo.list()}
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid in counts:
                item.setText(f"{counts[pid][0]}  ({counts[pid][1]})")

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            try:
                pid = self._repo.save(Profile(name.strip()))
            except ProfileError as exc:
                self.banner.show_message("error", str(exc))
                return
            self.reload_profiles(pid)

    def _rename_profile(self) -> None:
        if self._profile is None or self._locked():
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=self._profile.name)
        if ok and name.strip():
            old = self._profile.name
            self._profile.name = name.strip()
            if not self._persist():
                self._profile.name = old
            self.reload_profiles(self._profile.id)

    def _duplicate_profile(self) -> None:
        if self._profile and self._profile.id:
            self.reload_profiles(self._repo.duplicate(self._profile.id))

    def _delete_profile(self) -> None:
        if self._profile is None or self._locked():
            return
        if QMessageBox.question(self, "Delete profile", f"Delete profile '{self._profile.name}' and its actions?") \
                == QMessageBox.StandardButton.Yes:
            self._repo.delete(self._profile.id)
            if self._sessions.current_profile_id == self._profile.id:
                self._sessions.set_current_profile(None)
            self.reload_profiles()

    def _import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "PokePilot profile (*.json)")
        if path:
            self.import_from_file(path)

    def import_from_file(self, path: str) -> int | None:
        try:
            pid = self._repo.import_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, ProfileError) as exc:
            self.banner.show_message("error", f"Import failed: {exc}")
            return None
        self.reload_profiles(pid)
        problems = validate_profile(self._repo.get(pid), self._pg.layout)
        if problems:
            self.banner.show_message("warn", f"Imported with {len(problems)} issue(s) to fix against your calibration.")
        else:
            self.banner.show_message("ok", "Profile imported.")
        return pid

    def _export_profile(self) -> None:
        if self._profile is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", f"{self._profile.name}.json", "JSON (*.json)")
        if path:
            self.export_to_file(path)

    def export_to_file(self, path: str) -> bool:
        if self._profile is None:
            return False
        try:
            Path(path).write_text(self._profile.to_json(), encoding="utf-8")
        except OSError as exc:
            self.banner.show_message("error", f"Export failed: {exc}")
            return False
        self.banner.show_message("ok", f"Exported to {path}")
        return True

    def _save_description(self) -> None:
        if self._profile and self.desc_edit.text() != self._profile.description and not self._locked():
            self._profile.description = self.desc_edit.text()
            self._persist()

    # ------------------------------------------------------------ actions
    def _selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _add_action(self) -> None:
        if self._profile is None:
            self.banner.show_message("warn", "Create or select a profile first.")
            return
        if self._locked():
            return
        dlg = ActionDialog(self._pg.layout, None, self)
        if dlg.exec() and dlg.result_action:
            row = self._selected_row()
            pos = len(self._profile.actions) if row is None else row + 1
            self._profile.actions.insert(pos, dlg.result_action)
            self._persist()
            self.table.selectRow(pos)

    def _edit_action(self) -> None:
        row = self._selected_row()
        if self._profile is None or row is None or self._locked():
            return
        dlg = ActionDialog(self._pg.layout, self._profile.actions[row], self)
        if dlg.exec() and dlg.result_action:
            self._profile.actions[row] = dlg.result_action
            self._persist()
            self.table.selectRow(row)

    def _remove_action(self) -> None:
        row = self._selected_row()
        if self._profile is None or row is None or self._locked():
            return
        del self._profile.actions[row]
        self._persist()

    def _move(self, delta: int) -> None:
        row = self._selected_row()
        if self._profile is None or row is None or self._locked():
            return
        new = row + delta
        if 0 <= new < len(self._profile.actions):
            acts = self._profile.actions
            acts[row], acts[new] = acts[new], acts[row]
            self._persist()
            self.table.selectRow(new)

    def _render_actions(self) -> None:
        actions = self._profile.actions if self._profile else []
        self.table.setRowCount(len(actions))
        for row, a in enumerate(actions):
            self._render_row(row, a)
        self._refresh_validation()

    def _render_row(self, row: int, a: Action) -> None:
        vals = [str(row + 1), a.type.value, a.summary(), f"{a.timeout_s:g} s", a.expected_state or "-",
                a.error_policy.value + (f" x{a.max_retries}" if a.max_retries else ""), a.status.value]
        for col, v in enumerate(vals):
            item = QTableWidgetItem(v)
            if col == 6:
                item.setForeground(QColor(STATUS_COLORS[STATUS_LEVEL[a.status]]))
            self.table.setItem(row, col, item)

    def _refresh_validation(self) -> None:
        if self._profile is None:
            self.validation_label.setText("No profile selected.")
            return
        problems = validate_profile(self._profile, self._pg.layout)
        if problems:
            self.validation_label.setText("Cannot run yet:\n- " + "\n- ".join(problems[:6]))
            self.validation_label.setStyleSheet(f"color: {STATUS_COLORS['error']};")
        else:
            self.validation_label.setText("Profile is valid.")
            self.validation_label.setStyleSheet(f"color: {STATUS_COLORS['ok']};")

    # ------------------------------------------------------------ session
    def _start(self) -> None:
        if self._profile is None or self._profile.id is None:
            self.banner.show_message("warn", "Select a profile first.")
            return
        problems = validate_profile(self._profile, self._pg.layout)
        if problems:
            self.banner.show_message("error", f"Profile is not valid: {problems[0]}")
            return
        self.log_list.clear()
        self._sessions.start(self._profile.id)

    @Slot(object)
    def _on_started(self, profile: Profile) -> None:
        self._running_profile_id = profile.id
        if self._profile and self._profile.id == profile.id:
            for a in self._profile.actions:
                a.status = ActionStatus.PENDING
            self._render_actions()

    @Slot(object)
    def _on_state(self, state: SessionState) -> None:
        self.state_badge.set_status(STATE_LEVEL[state], state.value)
        self._update_buttons()
        self._update_info()

    def _update_buttons(self) -> None:
        state = self._sessions.state
        active = self._sessions.is_active and state in ACTIVE
        self.start_btn.setEnabled(not active and self._profile is not None)
        self.pause_btn.setEnabled(state is SessionState.RUNNING)
        self.resume_btn.setEnabled(state is SessionState.PAUSED)
        self.stop_btn.setEnabled(state in (SessionState.RUNNING, SessionState.PAUSED, SessionState.PREPARING))
        self.emergency_btn.setEnabled(active)

    def _update_info(self) -> None:
        s = self._sessions
        if s.is_active:
            text = f"Duration: {format_duration(s.started_at)}   Current: {s.current_action or '-'}"
        elif s.last_summary:
            r = s.last_summary
            text = (f"Last session: {r.result} - {r.succeeded} succeeded, {r.unknown} unverified, {r.failed} failed, "
                    f"{r.cancelled} cancelled.")
        else:
            text = "No session has run yet."
        if s.last_error:
            text += f"\nLast error: {s.last_error}"
        self.info_label.setText(text)

    @Slot(int, object)
    def _on_action_updated(self, index: int, action: Action) -> None:
        if self._profile and self._profile.id == self._running_profile_id and index < len(self._profile.actions):
            self._profile.actions[index].status = action.status
            self._render_row(index, self._profile.actions[index])

    @Slot(str, str)
    def _on_log(self, level: str, message: str) -> None:
        item = QListWidgetItem(f"{datetime.now():%H:%M:%S}  {level:<7} {message}")
        if level in ("ERROR", "WARNING"):
            item.setForeground(QColor(STATUS_COLORS["error" if level == "ERROR" else "warn"]))
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()
        while self.log_list.count() > 1000:
            self.log_list.takeItem(0)

    @Slot(object)
    def _on_finished(self, summary: SessionSummary) -> None:
        level = {"COMPLETED": "ok", "FAILED": "error"}.get(summary.result, "warn")
        self.banner.show_message(level, f"Session {summary.result}." + (f" {summary.last_error}" if summary.last_error else ""))
        self._update_buttons()
        self._update_info()
