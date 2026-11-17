"""Dashboard: live connection status, session controls and recent log entries."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QGridLayout, QGroupBox, QListWidget, QVBoxLayout, QWidget

from app.core.device_controller import AdbStatus, DeviceController
from app.emulator.models import AdbDevice
from app.ui.log_bridge import LogEntry, QtLogHandler
from app.ui.presenters import adb_status_display, device_display
from app.ui.widgets.common import Page, StatusCard, hbox, make_button

_SESSION_TOOLTIP = "Available when the automation engine is implemented (Phase 5)."
MAX_RECENT_LOGS = 100


class DashboardPage(Page):
    open_emulator_manager = Signal()

    def __init__(self, controller: DeviceController, log_handler: QtLogHandler, parent: QWidget | None = None) -> None:
        super().__init__("Dashboard", "Overview of the emulator connection and automation session.", parent)
        self._controller = controller

        grid = QGridLayout()
        grid.setSpacing(12)
        self.adb_card = StatusCard("ADB")
        self.device_card = StatusCard("Emulator / Device")
        self.pgsharp_card = StatusCard("PGSharp")
        self.mirror_card = StatusCard("Screen Mirroring")
        self.session_card = StatusCard("Automation Session")
        # Honest initial states: nothing has been checked for these modules yet.
        self.pgsharp_card.set_status("idle", "Not checked", "Use PGSharp Controller > Check Running.")
        self.mirror_card.set_status("idle", "Not running", "")
        self.session_card.set_status("idle", "Idle", "Profile: none")
        for i, card in enumerate(
            [self.adb_card, self.device_card, self.pgsharp_card, self.mirror_card, self.session_card]
        ):
            grid.addWidget(card, i // 3, i % 3)
        self.body.addLayout(grid)

        # Session controls - wired up in Phase 5; disabled rather than fake.
        controls = QGroupBox("Session Controls")
        self.start_btn = make_button("Start", "primary", _SESSION_TOOLTIP)
        self.pause_btn = make_button("Pause", tooltip=_SESSION_TOOLTIP)
        self.resume_btn = make_button("Resume", tooltip=_SESSION_TOOLTIP)
        self.stop_btn = make_button("Stop", tooltip=_SESSION_TOOLTIP)
        self.emergency_btn = make_button("Emergency Stop", "danger", _SESSION_TOOLTIP)
        self.session_buttons = [self.start_btn, self.pause_btn, self.resume_btn, self.stop_btn, self.emergency_btn]
        for b in self.session_buttons:
            b.setEnabled(False)
        cl = QVBoxLayout(controls)
        cl.addLayout(hbox(*self.session_buttons))

        actions = QGroupBox("Quick Actions")
        self.refresh_btn = make_button("Refresh Devices", "primary")
        self.manage_btn = make_button("Open Emulator Manager")
        self.refresh_btn.clicked.connect(controller.refresh_devices)
        self.manage_btn.clicked.connect(self.open_emulator_manager)
        al = QVBoxLayout(actions)
        al.addLayout(hbox(self.refresh_btn, self.manage_btn))

        row = hbox(controls, actions, stretch_end=False, spacing=12)
        self.body.addLayout(row)

        logs = QGroupBox("Recent Activity")
        self.log_list = QListWidget()
        self.log_list.setObjectName("LogList")
        ll = QVBoxLayout(logs)
        ll.addWidget(self.log_list)
        self.body.addWidget(logs, 1)

        for entry in log_handler.entries[-MAX_RECENT_LOGS:]:
            self._append_log(entry)
        log_handler.emitter.record.connect(self._append_log)

        controller.adb_status_changed.connect(self._on_adb_status)
        controller.devices_changed.connect(self._refresh_device_card)
        controller.selected_device_changed.connect(self._refresh_device_card)
        controller.busy_changed.connect(lambda busy: self.refresh_btn.setEnabled(not busy))
        self._on_adb_status(*controller.adb_status)
        self._refresh_device_card()

    def attach_pgsharp(self, apps, pg) -> None:  # noqa: ANN001 - AppController, PgsharpController
        from app.emulator.app_launcher import ProcessState

        levels = {ProcessState.RUNNING: "ok", ProcessState.NOT_RUNNING: "idle", ProcessState.UNKNOWN: "warn"}
        self._pg_state = ("idle", "Not checked")

        def render() -> None:
            lv = pg.last_verified
            detail = f"Package: {apps.target_package or 'not set'}"
            detail += f"\nLast verified: {lv[1]} at {lv[0]:%H:%M:%S}" if lv else "\nLast verified: none"
            self.pgsharp_card.set_status(*self._pg_state, detail)

        def on_proc(_serial: str, package: str, state: ProcessState) -> None:
            if package == apps.target_package:
                self._pg_state = (levels[state], f"Process: {state.value}")
                render()

        apps.process_state_changed.connect(on_proc)
        apps.target_app_changed.connect(lambda _p: render())
        pg.verification_done.connect(lambda _m: render())
        pg.feature_tested.connect(lambda _r: render())
        render()

    def attach_mirror(self, mirror) -> None:  # noqa: ANN001 - MirrorController
        from app.screen.mirror_controller import MirrorState

        levels = {MirrorState.RUNNING: "ok", MirrorState.FAILED: "error", MirrorState.STOPPED: "idle"}

        def update(state: MirrorState, detail: str) -> None:
            self.mirror_card.set_status(levels.get(state, "info"), state.value, detail)

        mirror.state_changed.connect(update)
        update(mirror.state, mirror.detail)

    @Slot(object, str)
    def _on_adb_status(self, status: AdbStatus, message: str) -> None:
        self.adb_card.set_status(adb_status_display(status), status.value, message)

    @Slot()
    def _refresh_device_card(self, *_: object) -> None:
        device: AdbDevice | None = self._controller.selected_device
        level, headline, detail = device_display(device, self._controller.selected_serial)
        count = len(self._controller.devices)
        if count > 1:
            detail += f"\n{count} devices detected."
        self.device_card.set_status(level, headline, detail)

    @Slot(object)
    def _append_log(self, entry: LogEntry) -> None:
        self.log_list.insertItem(0, entry.format())
        while self.log_list.count() > MAX_RECENT_LOGS:
            self.log_list.takeItem(self.log_list.count() - 1)
