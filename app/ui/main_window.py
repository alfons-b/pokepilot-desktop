"""Main window: sidebar navigation + stacked pages + status bar."""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.core.app_controller import AppController
from app.core.config import ConfigManager
from app.core.device_controller import AdbStatus, DeviceController
from app.core.task_runner import TaskRunner
from app.screen.mirror_controller import MirrorController
from app.ui.log_bridge import QtLogHandler
from app.ui.pages.activity_page import ActivityPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.emulator_page import EmulatorPage
from app.ui.pages.planned_page import PLANNED_PAGES, PlannedPage
from app.ui.pages.screen_page import ScreenPage
from app.ui.pages.settings_page import SettingsPage

logger = logging.getLogger(__name__)

NAV_ITEMS = [
    "Dashboard",
    "Emulator Manager",
    "Screen Monitor",
    "PGSharp Controller",
    "Automation Manager",
    "Location Manager",
    "Activity Monitor",
    "Settings",
]


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: DeviceController,
        runner: TaskRunner,
        config_manager: ConfigManager,
        log_handler: QtLogHandler,
        apps: AppController | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.runner = runner
        self.config_manager = config_manager
        self.apps = apps or AppController(controller, runner, self)
        self.mirror = MirrorController(controller, runner, self)
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1200, 780)
        self.setMinimumSize(960, 640)

        # Sidebar
        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.addItems(NAV_ITEMS)
        self.nav.setFixedWidth(220)
        self.nav.setCursor(Qt.CursorShape.PointingHandCursor)
        title = QLabel("PokePilot")
        title.setObjectName("SidebarTitle")
        version = QLabel(f"Desktop v{__version__}")
        version.setObjectName("SidebarVersion")
        side = QWidget()
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(title)
        sl.addWidget(version)
        sl.addWidget(self.nav, 1)

        # Pages
        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage(controller, log_handler)
        self.emulator_page = EmulatorPage(controller, self.apps)
        self.activity_page = ActivityPage(log_handler)
        self.settings_page = SettingsPage(controller, config_manager, self.mirror)
        self.screen_page = ScreenPage(controller, self.mirror)
        self.dashboard_page.attach_mirror(self.mirror)
        self.pages: dict[str, QWidget] = {
            "Dashboard": self.dashboard_page,
            "Emulator Manager": self.emulator_page,
            "Activity Monitor": self.activity_page,
            "Settings": self.settings_page,
            "Screen Monitor": self.screen_page,
        }
        for name, (phase, summary, feats) in PLANNED_PAGES.items():
            self.pages.setdefault(name, PlannedPage(name, phase, summary, feats))
        for name in NAV_ITEMS:
            self.stack.addWidget(self.pages[name])

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(side)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.dashboard_page.open_emulator_manager.connect(lambda: self.navigate_to("Emulator Manager"))
        self.nav.setCurrentRow(0)

        # Status bar
        self.adb_status_label = QLabel()
        self.device_status_label = QLabel()
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFixedWidth(90)
        self.busy_bar.setMaximumHeight(12)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        sb = self.statusBar()
        sb.addPermanentWidget(self.busy_bar)
        sb.addPermanentWidget(self.adb_status_label)
        sb.addPermanentWidget(self.device_status_label)

        controller.adb_status_changed.connect(self._update_adb_label)
        controller.selected_device_changed.connect(self._update_device_label)
        controller.devices_changed.connect(self._update_device_label)
        controller.busy_changed.connect(lambda _b: self._update_busy())
        self.apps.busy_changed.connect(lambda _b: self._update_busy())
        self.apps.operation_failed.connect(lambda op, msg: self._flash(f"{op} failed: {msg}", 10000))
        self.apps.operation_succeeded.connect(lambda op, msg: self._flash(f"{op}: {msg}", 6000))
        controller.operation_failed.connect(lambda op, msg: self._flash(f"{op} failed: {msg}", 10000))
        controller.operation_succeeded.connect(lambda op, msg: self._flash(f"{op}: {msg}", 6000))
        self._update_adb_label(*controller.adb_status)
        self._update_device_label()

        geometry = controller.config.window_geometry
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))

    def _flash(self, text: str, msecs: int) -> None:
        """Show a one-line, length-limited message (full text is in the page banner and log)."""
        line = " ".join(text.split())
        self.statusBar().showMessage(line if len(line) <= 110 else line[:107] + "...", msecs)

    def _update_busy(self) -> None:
        self.busy_bar.setVisible(self.controller.is_busy or self.apps.is_busy)

    def navigate_to(self, name: str) -> None:
        self.nav.setCurrentRow(NAV_ITEMS.index(name))

    @Slot(object, str)
    def _update_adb_label(self, status: AdbStatus, _message: str = "") -> None:
        self.adb_status_label.setText(f"ADB: {status.value}")

    @Slot()
    def _update_device_label(self, *_: object) -> None:
        serial = self.controller.selected_serial
        device = self.controller.selected_device
        if not serial:
            text = "Device: none"
        elif device is None:
            text = f"Device: {serial} (disconnected)"
        else:
            text = f"Device: {serial} ({device.raw_state})"
        self.device_status_label.setText(text)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self.settings_page.is_dirty():
            answer = QMessageBox.question(
                self,
                "Unsaved settings",
                "You have unsaved settings. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.controller.shutdown()
        self.mirror.shutdown()
        cfg = self.controller.config
        cfg.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        try:
            self.config_manager.save(cfg)
        except OSError as exc:
            logger.error("Could not save configuration on exit: %s", exc)
        if not self.runner.wait_for_done(5000):
            logger.warning("Background tasks still running at exit.")
        logger.info("PokePilot closed")
        event.accept()
