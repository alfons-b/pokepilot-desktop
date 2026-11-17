"""Application entry point and composition root."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __app_name__, __version__
from app.core.config import ConfigManager
from app.core.device_controller import DeviceController
from app.core.logging_setup import setup_logging
from app.core.task_runner import TaskRunner
from app.database.db import Database
from app.monitoring.history import SessionHistoryRepository
from app.monitoring.repositories import SettingsRepository
from app.paths import assets_dir, config_path, data_dir, logs_dir
from app.ui.log_bridge import QtLogHandler
from app.ui.main_window import MainWindow
from app.ui.theme import build_stylesheet

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    config_manager: ConfigManager
    runner: TaskRunner
    controller: DeviceController
    log_handler: QtLogHandler
    window: MainWindow
    startup_warnings: list[str]


def build_app(controller_kwargs: dict | None = None) -> AppContext:
    """Create every application object. Requires an existing QApplication."""
    config_manager = ConfigManager(config_path())
    load = config_manager.load()
    setup_logging(logs_dir(), load.config.log_level)

    log_handler = QtLogHandler()
    root = logging.getLogger()
    if not any(isinstance(h, QtLogHandler) for h in root.handlers):
        root.addHandler(log_handler)
    else:
        log_handler = next(h for h in root.handlers if isinstance(h, QtLogHandler))

    logger.info("Starting %s %s", __app_name__, __version__)
    for w in load.warnings:
        logger.warning("Configuration: %s", w)

    runner = TaskRunner()
    controller = DeviceController(config_manager, load.config, runner, **(controller_kwargs or {}))
    db = Database(data_dir() / "pokepilot.db")
    meta = SettingsRepository(db)
    if meta.get("first_run_at") is None:
        meta.set("first_run_at", datetime.now().isoformat(timespec="seconds"))
    previous = meta.get("app_version")
    if previous != __version__:
        logger.info("Application version %s (previous run: %s)", __version__, previous or "none")
        meta.set("app_version", __version__)
    interrupted = SessionHistoryRepository(db).mark_interrupted()
    if interrupted:
        logger.warning("%d session(s) from a previous run did not finish cleanly (marked INTERRUPTED).", interrupted)
    window = MainWindow(controller, runner, config_manager, log_handler, db=db)
    warnings = list(load.warnings) if load.recovered_from_corruption else []
    if db.recovered_from:
        warnings.append(f"The database was damaged and has been reset. The old file was saved as {db.recovered_from.name}.")
    return AppContext(config_manager, runner, controller, log_handler, window, warnings)


def _start(ctx: AppContext) -> None:
    for warning in ctx.startup_warnings:
        QMessageBox.warning(ctx.window, "Configuration recovered", warning)
    if ctx.controller.config.adb_path:
        ctx.controller.refresh_devices()
    else:
        logger.info("No ADB path configured; trying auto-detection.")
        ctx.controller.auto_detect_adb()
    ctx.controller.apply_refresh_settings()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    smoke_test = "--smoke-test" in argv  # start everything, then exit: used to verify packaged builds
    if smoke_test:
        argv.remove("--smoke-test")
    app = QApplication(argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PokePilot")
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
    icon = assets_dir() / "icons" / "app.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    def excepthook(exc_type, exc, tb) -> None:  # noqa: ANN001
        logging.getLogger("app").critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        QMessageBox.critical(None, "Unexpected error", f"{exc_type.__name__}: {exc}\n\nSee the log for details.")

    sys.excepthook = excepthook

    ctx = build_app()
    ctx.window.show()
    if smoke_test:
        logger.info("Smoke test: application started; exiting in 2 s.")
        QTimer.singleShot(2000, ctx.window.close)
        QTimer.singleShot(2500, app.quit)
    else:
        QTimer.singleShot(0, lambda: _start(ctx))
    code = app.exec()
    ctx.runner.wait_for_done(5000)
    return code


if __name__ == "__main__":
    sys.exit(main())
