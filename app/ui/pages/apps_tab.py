"""Applications tab: list installed packages, choose the target app, launch/stop it."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.emulator.app_launcher import ProcessState
from app.ui.widgets.common import StatusBadge, hbox, make_button

_STATE_LEVEL = {ProcessState.RUNNING: "ok", ProcessState.NOT_RUNNING: "idle", ProcessState.UNKNOWN: "warn"}


class AppsTab(QWidget):
    def __init__(self, devices: DeviceController, apps: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        self._apps = apps
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        target_box = QGroupBox("Target App")
        self.target_label = QLabel()
        self.state_badge = StatusBadge("Not checked", "idle")
        self.launch_btn = make_button("Launch", "primary", "Start the target app and confirm its process is running.")
        self.check_btn = make_button("Check Running", tooltip="Check whether the app's process is running (pidof).")
        self.stop_btn = make_button("Force Stop", tooltip="am force-stop the target app.")
        self.launch_btn.clicked.connect(apps.launch_target)
        self.check_btn.clicked.connect(apps.check_target_running)
        self.stop_btn.clicked.connect(self._confirm_stop)
        note = QLabel(
            "Choose the app PokePilot should launch (for example your PGSharp installation). "
            "'Running' means the app process exists; it does not confirm what is on screen."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        tl = QVBoxLayout(target_box)
        tl.addLayout(hbox(self.target_label, self.state_badge))
        tl.addLayout(hbox(self.launch_btn, self.check_btn, self.stop_btn))
        tl.addWidget(note)
        layout.addWidget(target_box)

        list_box = QGroupBox("Installed Apps")
        self.load_btn = make_button("Load Apps", tooltip="pm list packages on the selected device.")
        self.system_check = QCheckBox("Include system apps")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter, e.g. pokemongo")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._set_target())
        self.set_target_btn = make_button("Set as Target App")
        self.set_target_btn.clicked.connect(self._set_target)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        self.load_btn.clicked.connect(lambda: apps.load_packages(self.system_check.isChecked()))
        ll = QVBoxLayout(list_box)
        ll.addLayout(hbox(self.load_btn, self.system_check, self.search_edit, stretch_end=False))
        ll.addWidget(self.list, 1)
        ll.addLayout(hbox(self.set_target_btn, self.count_label))
        layout.addWidget(list_box, 1)

        self._all: list[str] = []
        apps.packages_loaded.connect(self._on_packages)
        apps.target_app_changed.connect(lambda _p: self._refresh_target())
        apps.process_state_changed.connect(self._on_state)
        apps.busy_changed.connect(self._on_busy)
        devices.selected_device_changed.connect(self._on_device_changed)
        self._refresh_target()

    def _refresh_target(self) -> None:
        pkg = self._apps.target_package
        self.target_label.setText(f"<b>{pkg}</b>" if pkg else "No target app selected")
        self.state_badge.set_status("idle", "Not checked")
        for b in (self.launch_btn, self.check_btn, self.stop_btn):
            b.setEnabled(bool(pkg) and not self._apps.is_busy)

    def _set_target(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self._apps.set_target_package(item.text())

    def _confirm_stop(self) -> None:
        pkg = self._apps.target_package
        answer = QMessageBox.question(self, "Force stop", f"Force stop {pkg}? Unsaved state in the app is lost.")
        if answer == QMessageBox.StandardButton.Yes:
            self._apps.stop_target()

    @Slot(str, list)
    def _on_packages(self, serial: str, pkgs: list[str]) -> None:
        self._all = pkgs
        self._apply_filter()

    def _apply_filter(self, *_: object) -> None:
        needle = self.search_edit.text().strip().lower()
        shown = [p for p in self._all if needle in p.lower()]
        self.list.clear()
        self.list.addItems(shown)
        self.count_label.setText(f"{len(shown)} of {len(self._all)} apps" if self._all else "")

    @Slot(str, str, object)
    def _on_state(self, serial: str, package: str, state: ProcessState) -> None:
        if package == self._apps.target_package:
            self.state_badge.set_status(_STATE_LEVEL[state], state.value)

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        self.load_btn.setEnabled(not busy)
        has_target = bool(self._apps.target_package)
        for b in (self.launch_btn, self.check_btn, self.stop_btn):
            b.setEnabled(has_target and not busy)

    @Slot(object)
    def _on_device_changed(self, _serial: object) -> None:
        self._all = []
        self._apply_filter()
        self.state_badge.set_status("idle", "Not checked")
