"""Settings: ADB path, emulator executable, scrcpy path, refresh and logging."""

from __future__ import annotations

import sys

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.config import NUMERIC_RANGES, VALID_LOG_LEVELS, AppConfig, ConfigManager
from app.core.device_controller import DeviceController
from app.core.logging_setup import set_log_level
from app.emulator.emulator_launcher import EmulatorLaunchError, split_args
from app.ui.widgets.common import Banner, Page, hbox, make_button

_EXE_FILTER = "Executables (*.exe);;All files (*)" if sys.platform == "win32" else "All files (*)"


class SettingsPage(Page):
    settings_saved = Signal()

    def __init__(
        self, controller: DeviceController, config_manager: ConfigManager, parent: QWidget | None = None
    ) -> None:
        super().__init__("Settings", "Paths to external tools and application behaviour.", parent)
        self._controller = controller
        self._config_manager = config_manager
        self.banner = Banner()
        self.body.addWidget(self.banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("Page")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        scroll.setWidget(content)
        self.body.addWidget(scroll, 1)

        # ADB
        adb_box = QGroupBox("Android Debug Bridge (ADB)")
        self.adb_path_edit = QLineEdit()
        self.adb_path_edit.setPlaceholderText(r"C:\platform-tools\adb.exe")
        self.adb_browse_btn = make_button("Browse...")
        self.adb_detect_btn = make_button("Auto-detect", tooltip="Search PATH, the Android SDK and emulator folders.")
        self.adb_test_btn = make_button("Test", tooltip="Run 'adb version' with the path above.")
        self.adb_browse_btn.clicked.connect(lambda: self._browse(self.adb_path_edit, "Select adb executable"))
        self.adb_detect_btn.clicked.connect(controller.auto_detect_adb)
        self.adb_test_btn.clicked.connect(lambda: controller.test_adb(self.adb_path_edit.text()))
        self.timeout_spin = QDoubleSpinBox()
        lo, hi = NUMERIC_RANGES["adb_command_timeout_s"]
        self.timeout_spin.setRange(lo, hi)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setDecimals(0)
        self.timeout_spin.setFixedWidth(120)
        f = QFormLayout(adb_box)
        f.addRow("ADB executable:", self.adb_path_edit)
        f.addRow("", hbox(self.adb_browse_btn, self.adb_detect_btn, self.adb_test_btn))
        f.addRow("Command timeout:", self.timeout_spin)
        col.addWidget(adb_box)

        # Devices
        dev_box = QGroupBox("Device Detection")
        self.auto_refresh_check = QCheckBox("Automatically refresh the device list")
        self.refresh_spin = QSpinBox()
        lo, hi = NUMERIC_RANGES["auto_refresh_interval_s"]
        self.refresh_spin.setRange(int(lo), int(hi))
        self.refresh_spin.setSuffix(" s")
        self.refresh_spin.setFixedWidth(120)
        self.auto_refresh_check.toggled.connect(self.refresh_spin.setEnabled)
        self.auto_reconnect_check = QCheckBox("Automatically reconnect TCP/IP devices (e.g. BlueStacks) when they drop")
        f = QFormLayout(dev_box)
        f.addRow(self.auto_refresh_check)
        f.addRow("Refresh interval:", self.refresh_spin)
        f.addRow(self.auto_reconnect_check)
        col.addWidget(dev_box)

        # Emulator
        emu_box = QGroupBox("Emulator")
        self.emu_path_edit = QLineEdit()
        self.emu_path_edit.setPlaceholderText("Path to your emulator's launcher executable")
        self.emu_browse_btn = make_button("Browse...")
        self.emu_browse_btn.clicked.connect(lambda: self._browse(self.emu_path_edit, "Select emulator executable"))
        self.emu_args_edit = QLineEdit()
        self.emu_args_edit.setPlaceholderText('Optional, e.g. --instance "Pie64"')
        self.bs_conf_edit = QLineEdit()
        self.bs_conf_edit.setPlaceholderText(r"Auto: C:\ProgramData\BlueStacks_nxt\bluestacks.conf")
        self.bs_conf_browse_btn = make_button("Browse...")
        self.bs_conf_browse_btn.clicked.connect(
            lambda: self._browse(self.bs_conf_edit, "Select bluestacks.conf", "Config (*.conf);;All files (*)")
        )
        f = QFormLayout(emu_box)
        f.addRow("Executable:", hbox(self.emu_path_edit, self.emu_browse_btn, stretch_end=False))
        f.addRow("Arguments:", self.emu_args_edit)
        f.addRow("BlueStacks config:", hbox(self.bs_conf_edit, self.bs_conf_browse_btn, stretch_end=False))
        col.addWidget(emu_box)

        # scrcpy
        scrcpy_box = QGroupBox("Screen Mirroring (scrcpy)")
        self.scrcpy_path_edit = QLineEdit()
        self.scrcpy_path_edit.setPlaceholderText(r"C:\scrcpy\scrcpy.exe  (used from Phase 3)")
        self.scrcpy_browse_btn = make_button("Browse...")
        self.scrcpy_browse_btn.clicked.connect(lambda: self._browse(self.scrcpy_path_edit, "Select scrcpy executable"))
        f = QFormLayout(scrcpy_box)
        f.addRow("scrcpy executable:", hbox(self.scrcpy_path_edit, self.scrcpy_browse_btn, stretch_end=False))
        col.addWidget(scrcpy_box)

        # Logging
        log_box = QGroupBox("Logging")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(VALID_LOG_LEVELS)
        self.log_level_combo.setFixedWidth(160)
        f = QFormLayout(log_box)
        f.addRow("Log level:", self.log_level_combo)
        col.addWidget(log_box)
        col.addStretch(1)

        self.save_btn = make_button("Save Settings", "primary")
        self.revert_btn = make_button("Revert")
        self.save_btn.clicked.connect(self.save)
        self.revert_btn.clicked.connect(self._confirm_revert)
        self.body.addLayout(hbox(self.save_btn, self.revert_btn))

        controller.adb_path_changed.connect(self.adb_path_edit.setText)
        controller.operation_succeeded.connect(self._on_success)
        controller.operation_failed.connect(self._on_failure)
        controller.busy_changed.connect(self._on_busy)
        self.load_from_config(controller.config)

    # ----------------------------------------------------------- data flow
    def load_from_config(self, cfg: AppConfig) -> None:
        self.adb_path_edit.setText(cfg.adb_path)
        self.timeout_spin.setValue(cfg.adb_command_timeout_s)
        self.auto_refresh_check.setChecked(cfg.auto_refresh_enabled)
        self.refresh_spin.setValue(cfg.auto_refresh_interval_s)
        self.refresh_spin.setEnabled(cfg.auto_refresh_enabled)
        self.auto_reconnect_check.setChecked(cfg.auto_reconnect_enabled)
        self.bs_conf_edit.setText(cfg.bluestacks_conf_path)
        self.emu_path_edit.setText(cfg.emulator_path)
        self.emu_args_edit.setText(cfg.emulator_args)
        self.scrcpy_path_edit.setText(cfg.scrcpy_path)
        self.log_level_combo.setCurrentText(cfg.log_level)

    def is_dirty(self) -> bool:
        c = self._controller.config
        return (
            self.adb_path_edit.text().strip() != c.adb_path
            or self.timeout_spin.value() != c.adb_command_timeout_s
            or self.auto_refresh_check.isChecked() != c.auto_refresh_enabled
            or self.refresh_spin.value() != c.auto_refresh_interval_s
            or self.emu_path_edit.text().strip() != c.emulator_path
            or self.emu_args_edit.text() != c.emulator_args
            or self.scrcpy_path_edit.text().strip() != c.scrcpy_path
            or self.log_level_combo.currentText() != c.log_level
            or self.auto_reconnect_check.isChecked() != c.auto_reconnect_enabled
            or self.bs_conf_edit.text().strip() != c.bluestacks_conf_path
        )

    def save(self) -> bool:
        try:
            split_args(self.emu_args_edit.text())
        except EmulatorLaunchError as exc:
            self.banner.show_message("error", str(exc))
            return False

        cfg = self._controller.config
        old_adb = cfg.adb_path
        cfg.adb_command_timeout_s = float(self.timeout_spin.value())
        cfg.auto_refresh_enabled = self.auto_refresh_check.isChecked()
        cfg.auto_refresh_interval_s = int(self.refresh_spin.value())
        cfg.emulator_path = self.emu_path_edit.text().strip()
        cfg.emulator_args = self.emu_args_edit.text().strip()
        cfg.scrcpy_path = self.scrcpy_path_edit.text().strip()
        cfg.log_level = self.log_level_combo.currentText()
        cfg.auto_reconnect_enabled = self.auto_reconnect_check.isChecked()
        cfg.bluestacks_conf_path = self.bs_conf_edit.text().strip()
        try:
            # set_adb_path saves if the path changed; save once more for the other fields.
            self._controller.set_adb_path(self.adb_path_edit.text())
            self._config_manager.save(cfg)
        except OSError as exc:
            self.banner.show_message("error", f"Could not save settings: {exc}")
            return False
        set_log_level(cfg.log_level)
        self._controller.apply_refresh_settings()
        if cfg.adb_path != old_adb:
            self._controller.refresh_devices()
        self.load_from_config(cfg)
        self.banner.show_message("ok", "Settings saved.")
        self.settings_saved.emit()
        return True

    def _confirm_revert(self) -> None:
        if not self.is_dirty():
            return
        answer = QMessageBox.question(self, "Revert settings", "Discard unsaved changes?")
        if answer == QMessageBox.StandardButton.Yes:
            self.load_from_config(self._controller.config)

    def _browse(self, target: QLineEdit, title: str, file_filter: str = _EXE_FILTER) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, target.text(), file_filter)
        if path:
            target.setText(path)

    # ------------------------------------------------------------ signals
    @Slot(str, str)
    def _on_success(self, op: str, message: str) -> None:
        if op in ("Test ADB", "Auto-detect ADB"):
            self.banner.show_message("ok", message)

    @Slot(str, str)
    def _on_failure(self, op: str, message: str) -> None:
        if op in ("Test ADB", "Auto-detect ADB", "Save settings"):
            self.banner.show_message("error", f"{op} failed: {message}")

    @Slot(bool)
    def _on_busy(self, busy: bool) -> None:
        self.adb_detect_btn.setEnabled(not busy)
        self.adb_test_btn.setEnabled(not busy)
