"""Emulator Instances tab: discover BlueStacks instances and their ADB ports."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.device_controller import DeviceController
from app.emulator.instances import DiscoveryResult, EmulatorInstance
from app.ui.widgets.common import hbox, make_button

COLUMNS = ["Emulator", "Instance", "Name", "ADB address", "ADB access", "Connected"]


class InstancesTab(QWidget):
    def __init__(self, devices: DeviceController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        self._instances: list[EmulatorInstance] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        box = QGroupBox("Emulator Instances")
        self.scan_btn = make_button("Scan", "primary", "Read instance list and ADB ports from BlueStacks' config file.")
        self.connect_btn = make_button("Connect")
        self.launch_btn = make_button("Launch Instance")
        self.default_btn = make_button(
            "Use as Default", tooltip="Store this instance as the emulator launcher and preferred device."
        )
        self.scan_btn.clicked.connect(devices.discover_instances)
        self.connect_btn.clicked.connect(lambda: self._with_selected(devices.connect_instance))
        self.launch_btn.clicked.connect(lambda: self._with_selected(devices.launch_instance))
        self.default_btn.clicked.connect(lambda: self._with_selected(devices.use_instance_as_launcher))

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.info_label = QLabel(
            "Supported: BlueStacks 5 (incl. MSI App Player). For other emulators, use Connect over TCP/IP on "
            "the Devices tab."
        )
        self.info_label.setObjectName("Muted")
        self.info_label.setWordWrap(True)
        self.warn_label = QLabel("")
        self.warn_label.setObjectName("Banner")
        self.warn_label.setProperty("level", "warn")
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()

        bl = QVBoxLayout(box)
        bl.addLayout(hbox(self.scan_btn, self.connect_btn, self.launch_btn, self.default_btn))
        bl.addWidget(self.warn_label)
        bl.addWidget(self.table, 1)
        bl.addWidget(self.info_label)
        layout.addWidget(box, 1)

        devices.instances_discovered.connect(self._on_discovered)
        devices.devices_changed.connect(lambda _d: self._populate())
        devices.busy_changed.connect(lambda _b: self._update_buttons())
        self._update_buttons()

    def selected_instance(self) -> EmulatorInstance | None:
        rows = self.table.selectionModel().selectedRows()
        return self._instances[rows[0].row()] if rows else None

    def _with_selected(self, fn) -> None:  # noqa: ANN001
        inst = self.selected_instance()
        if inst is not None:
            fn(inst)

    @Slot(object)
    def _on_discovered(self, result: DiscoveryResult) -> None:
        self._instances = result.instances
        msgs = list(result.warnings)
        if not result.sources:
            msgs.append(
                "No BlueStacks configuration was found. If BlueStacks is installed in a custom location, set the "
                "bluestacks.conf path in Settings."
            )
        self.warn_label.setText("\n".join(msgs))
        self.warn_label.setVisible(bool(msgs))
        self.warn_label.style().unpolish(self.warn_label)
        self.warn_label.style().polish(self.warn_label)
        self._populate()

    def _populate(self) -> None:
        online = {d.serial for d in self._devices.devices if d.is_online}
        self.table.setRowCount(len(self._instances))
        for row, inst in enumerate(self._instances):
            access = {True: "Enabled", False: "Disabled", None: "Unknown"}[inst.adb_enabled]
            connected = "Yes" if inst.adb_address in online else "No"
            for col, text in enumerate(
                [inst.provider, inst.name, inst.display_name, inst.adb_address or "Unknown", access, connected]
            ):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self._update_buttons()

    def _update_buttons(self) -> None:
        inst = self.selected_instance()
        busy = self._devices.is_busy
        self.scan_btn.setEnabled(not busy)
        self.connect_btn.setEnabled(bool(inst and inst.adb_address) and not busy)
        self.launch_btn.setEnabled(bool(inst and inst.can_launch) and not busy)
        self.default_btn.setEnabled(bool(inst and inst.can_launch))
