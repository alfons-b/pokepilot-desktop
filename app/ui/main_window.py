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
from app.automation.repository import ProfileRepository
from app.automation.session_manager import SessionManager
from app.core.app_controller import AppController
from app.core.config import ConfigManager
from app.core.device_controller import AdbStatus, DeviceController
from app.core.task_runner import TaskRunner
from app.database.db import Database
from app.locations.repository import GpxRepository, LocationRepository
from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository
from app.monitoring.monitor import StatusMonitor
from app.monitoring.repositories import DatabaseLogHandler, DeviceRepository, EmulatorConfigRepository
from app.paths import data_dir
from app.pgsharp.controller import PgsharpController
from app.screen.mirror_controller import MirrorController
from app.ui.log_bridge import QtLogHandler
from app.ui.pages.activity_page import ActivityPage
from app.ui.pages.automation_page import AutomationPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.emulator_page import EmulatorPage
from app.ui.pages.location_page import LocationPage
from app.ui.pages.pgsharp_page import PgsharpPage
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
        db: Database | None = None,
    ) -> None:
        super().__init__()
        self.db = db or Database(":memory:")
        self.history = SessionHistoryRepository(self.db)
        self.activity_logs = ActivityLogRepository(self.db)
        self.controller = controller
        self.runner = runner
        self.config_manager = config_manager
        self.apps = apps or AppController(controller, runner, self)
        self.mirror = MirrorController(controller, runner, self)
        self.pgsharp = PgsharpController(controller, runner, parent=self)
        self.sessions = SessionManager(
            controller, self.apps, self.pgsharp, ProfileRepository(self.db), self.history, self.activity_logs, parent=self
        )
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
        self.settings_page = SettingsPage(controller, config_manager, self.mirror)
        self.screen_page = ScreenPage(controller, self.mirror)
        self.pgsharp_page = PgsharpPage(self.pgsharp, self.apps)
        self.automation_page = AutomationPage(self.sessions, self.pgsharp)
        self.location_page = LocationPage(LocationRepository(self.db), GpxRepository(self.db, data_dir() / "gpx"))
        self.monitor = StatusMonitor(controller, self.apps, self.mirror, self.pgsharp, self.sessions, runner, self)
        self.activity_page = ActivityPage(log_handler, self.monitor, self.history, self.activity_logs)
        self._wire_persistence()
        self.dashboard_page.attach_sessions(self.sessions)
        self.sessions.confirmation_requested.connect(self._ask_confirmation)
        self.dashboard_page.attach_pgsharp(self.apps, self.pgsharp)
        self.dashboard_page.attach_mirror(self.mirror)
        self.pages: dict[str, QWidget] = {
            "Dashboard": self.dashboard_page,
            "Emulator Manager": self.emulator_page,
            "Activity Monitor": self.activity_page,
            "Settings": self.settings_page,
            "Screen Monitor": self.screen_page,
            "PGSharp Controller": self.pgsharp_page,
            "Automation Manager": self.automation_page,
            "Location Manager": self.location_page,
        }
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

    def _wire_persistence(self) -> None:
        """Record devices, emulator instances and warnings/errors in the database."""
        devices_repo = DeviceRepository(self.db)
        emu_repo = EmulatorConfigRepository(self.db)

        def safe(fn):  # noqa: ANN001, ANN202
            def wrapper(*args: object) -> None:
                try:
                    fn(*args)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("database write failed: %s", exc)
            return wrapper

        self.controller.devices_changed.connect(safe(devices_repo.upsert_seen))
        self.controller.device_info_ready.connect(safe(devices_repo.update_info))
        self.controller.instances_discovered.connect(safe(lambda r: emu_repo.upsert(r.instances)))
        root = logging.getLogger()
        for h in [h for h in root.handlers if isinstance(h, DatabaseLogHandler)]:
            root.removeHandler(h)
        self.db_log_handler = DatabaseLogHandler(self.activity_logs)
        self.db_log_handler.session_id_provider = lambda: self.sessions.session_id
        root.addHandler(self.db_log_handler)
        self.monitor.start()

    def _flash(self, text: str, msecs: int) -> None:
        """Show a one-line, length-limited message (full text is in the page banner and log)."""
        line = " ".join(text.split())
        self.statusBar().showMessage(line if len(line) <= 110 else line[:107] + "...", msecs)

    def _update_busy(self) -> None:
        self.busy_bar.setVisible(self.controller.is_busy or self.apps.is_busy)

    def _ask_confirmation(self, message: str) -> None:
        """USER_CONFIRMATION action: ask on the GUI thread, answer the worker."""
        box = QMessageBox(QMessageBox.Icon.Question, "Automation confirmation", message,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        self.sessions.state_changed.connect(lambda st: box.reject() if st.value in ("IDLE", "FAILED") else None)
        answer = box.exec()
        self.sessions.respond_confirmation(answer == QMessageBox.StandardButton.Yes)

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
        if self.sessions.is_active:
            answer = QMessageBox.question(
                self,
                "Session running",
                "An automation session is running. Stop it immediately and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.sessions.shutdown()
        self.monitor.stop()
        logging.getLogger().removeHandler(self.db_log_handler)
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
        self.db.close()
        event.accept()
