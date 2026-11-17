"""Emulator Manager: device discovery, selection, TCP connect and device info."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.device_controller import AdbStatus, DeviceController
from app.emulator.models import AdbDevice, DeviceInfo
from app.ui.presenters import device_state_display
from app.ui.theme import STATUS_COLORS
from app.ui.widgets.common import Banner, Page, hbox, make_button

COLUMNS = ["Serial", "State", "Model", "Product", "Connection", "Emulator hint"]

CONNECT_HINT = (
    "Many emulators expose ADB over TCP and need a one-time connect. Typical local ports "
    "(check your emulator's settings): 5555, 5556, 7555, 16384, 21503, 62001. "
    "Emulators listed as 'emulator-NNNN' connect automatically."
)


class EmulatorPage(Page):
    def __init__(self, controller: DeviceController, parent: QWidget | None = None) -> None:
        super().__init__(
            "Emulator Manager",
            "Detect Android emulators through ADB and choose the device PokePilot controls.",
            parent,
        )
        self._controller = controller
        self.banner = Banner()
        self.body.addWidget(self.banner)

        # Toolbar
        self.refresh_btn = make_button("Refresh", "primary", "Scan for devices with 'adb devices'.")
        self.restart_btn = make_button("Restart ADB Server", tooltip="Runs adb kill-server and start-server.")
        self.launch_btn = make_button("Launch Emulator", tooltip="Starts the emulator configured in Settings.")
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("Muted")
        self.refresh_btn.clicked.connect(controller.refresh_devices)
        self.restart_btn.clicked.connect(self._confirm_restart)
        self.launch_btn.clicked.connect(controller.launch_emulator)
        self.body.addLayout(hbox(self.refresh_btn, self.restart_btn, self.launch_btn, self.busy_label))

        # Connect by address
        connect_box = QGroupBox("Connect over TCP/IP")
        self.address_combo = QComboBox()
        self.address_combo.setEditable(True)
        self.address_combo.setMinimumWidth(240)
        self.address_combo.lineEdit().setPlaceholderText("127.0.0.1:5555")
        self.address_combo.lineEdit().returnPressed.connect(self._connect)
        self.connect_btn = make_button("Connect")
        self.connect_btn.clicked.connect(self._connect)
        hint = QLabel(CONNECT_HINT)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        cb = QVBoxLayout(connect_box)
        cb.addLayout(hbox(QLabel("Address:"), self.address_combo, self.connect_btn))
        cb.addWidget(hint)
        self.body.addWidget(connect_box)
        self._reload_addresses()

        # Devices table
        devices_box = QGroupBox("Detected Devices")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        self.empty_label = QLabel("No devices detected. Start your emulator, then press Refresh.")
        self.empty_label.setObjectName("Muted")
        self.selected_label = QLabel("Selected device: none")
        db = QVBoxLayout(devices_box)
        db.addWidget(self.table)
        db.addWidget(self.empty_label)
        db.addWidget(self.selected_label)
        self.body.addWidget(devices_box, 1)

        # Device info
        info_box = QGroupBox("Device Information")
        self.info_btn = make_button("Read Device Info", tooltip="Reads getprop and wm size from the selected device.")
        self.info_btn.clicked.connect(lambda: controller.fetch_device_info())
        self.info_fields: dict[str, QLabel] = {}
        form = QFormLayout()
        for key, label in [
            ("android", "Android version"),
            ("sdk", "API level"),
            ("manufacturer", "Manufacturer"),
            ("model", "Model"),
            ("abi", "CPU ABI"),
            ("resolution", "Screen resolution"),
            ("qemu", "QEMU flag"),
        ]:
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.info_fields[key] = value
            form.addRow(f"{label}:", value)
        ib = QVBoxLayout(info_box)
        ib.addLayout(hbox(self.info_btn))
        ib.addLayout(form)
        self.body.addWidget(info_box)

        controller.devices_changed.connect(self._populate)
        controller.selected_device_changed.connect(self._on_selected_changed)
        controller.device_info_ready.connect(self._show_info)
        controller.busy_changed.connect(self._on_busy)
        controller.operation_succeeded.connect(self._on_success)
        controller.operation_failed.connect(self._on_failure)
        controller.adb_status_changed.connect(self._on_adb_status)
        self._populate(controller.devices)

    # ------------------------------------------------------------ actions
    def _confirm_restart(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restart ADB server",
            "Restarting the ADB server disconnects all devices, including TCP connections, "
            "which may need to be connected again.\n\nContinue?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.restart_adb_server()

    def _connect(self) -> None:
        address = self.address_combo.currentText().strip()
        if not address:
            self.banner.show_message("warn", "Enter an address such as 127.0.0.1:5555.")
            return
        self._controller.connect_address(address)

    def _reload_addresses(self) -> None:
        current = self.address_combo.currentText()
        self.address_combo.blockSignals(True)
        self.address_combo.clear()
        self.address_combo.addItems(self._controller.config.recent_connect_addresses)
        self.address_combo.setEditText(current)
        self.address_combo.blockSignals(False)

    # ------------------------------------------------------------ updates
    @Slot(list)
    def _populate(self, devices: list[AdbDevice]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            values = [
                d.serial,
                d.raw_state or d.state.value,
                d.model.replace("_", " "),
                d.product,
                d.connection_type,
                "Likely emulator" if d.is_emulator_hint else "-",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, d.serial)
                if col == 1:
                    item.setForeground(QColor(STATUS_COLORS.get(device_state_display(d.state), STATUS_COLORS["idle"])))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.table.setVisible(bool(devices))
        self.empty_label.setVisible(not devices)
        self._on_selected_changed(self._controller.selected_serial)

    @Slot(object)
    def _on_selected_changed(self, serial: str | None) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == serial:
                self.table.selectRow(row)
                break
        self.table.blockSignals(False)
        device = self._controller.selected_device
        if not serial:
            self.selected_label.setText("Selected device: none")
        elif device is None:
            self.selected_label.setText(f"Selected device: {serial} (not connected)")
        else:
            self.selected_label.setText(f"Selected device: {device.display_name} - {device.raw_state}")
        self.info_btn.setEnabled(bool(device and device.is_online) and not self._controller.is_busy)
        if self._controller.last_device_info is None:
            self._clear_info()

    def _on_table_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            item = self.table.item(rows[0].row(), 0)
            if item:
                self._controller.select_device(item.text())

    @Slot(object)
    def _show_info(self, info: DeviceInfo) -> None:
        f = self.info_fields
        f["android"].setText(info.android_version or "Unknown")
        f["sdk"].setText(info.sdk_level or "Unknown")
        f["manufacturer"].setText(info.manufacturer or "Unknown")
        f["model"].setText(info.model or "Unknown")
        f["abi"].setText(info.abi or "Unknown")
        res = DeviceInfo.format_resolution(info.physical_resolution)
        if info.override_resolution:
            res += f" (override {DeviceInfo.format_resolution(info.override_resolution)})"
        f["resolution"].setText(res)
        f["qemu"].setText("Set (QEMU-based emulator)" if info.qemu_flag else "Not set")

    def _clear_info(self) -> None:
        for label in self.info_fields.values():
            label.setText("-")

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        self.busy_label.setText("Working..." if busy else "")
        for b in (self.refresh_btn, self.restart_btn, self.connect_btn, self.launch_btn):
            b.setEnabled(not busy)
        device = self._controller.selected_device
        self.info_btn.setEnabled(not busy and bool(device and device.is_online))

    @Slot(str, str)
    def _on_success(self, op: str, message: str) -> None:
        self.banner.show_message("ok", f"{op}: {message}")
        if op == "Connect":
            self._reload_addresses()

    @Slot(str, str)
    def _on_failure(self, op: str, message: str) -> None:
        self.banner.show_message("error", f"{op} failed: {message}")

    @Slot(object, str)
    def _on_adb_status(self, status: AdbStatus, message: str) -> None:
        if status in (AdbStatus.NOT_CONFIGURED, AdbStatus.NOT_FOUND):
            self.banner.show_message("warn", f"ADB {status.value.lower()}: {message}")

