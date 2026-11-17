"""Android application discovery and launching for the selected device."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.emulator import app_launcher
from app.emulator.app_launcher import LaunchResult, ProcessState, validate_package_name

logger = logging.getLogger(__name__)


class AppController(QObject):
    packages_loaded = Signal(str, list)  # serial, packages
    target_app_changed = Signal(str)
    process_state_changed = Signal(str, str, object)  # serial, package, ProcessState
    launch_finished = Signal(object)  # LaunchResult
    operation_succeeded = Signal(str, str)
    operation_failed = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, devices: DeviceController, runner: TaskRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        self._runner = runner
        self._busy = 0
        self._packages: dict[str, list[str]] = {}
        devices.selected_device_changed.connect(lambda _s: self._packages.clear())

    @property
    def target_package(self) -> str:
        return self._devices.config.target_app_package

    @property
    def is_busy(self) -> bool:
        return self._busy > 0

    def packages_for(self, serial: str) -> list[str]:
        return list(self._packages.get(serial, []))

    def set_target_package(self, package: str) -> bool:
        try:
            package = validate_package_name(package)
        except ValueError as exc:
            self.operation_failed.emit("Set target app", str(exc))
            return False
        cfg = self._devices.config
        if cfg.target_app_package != package:
            cfg.target_app_package = package
            if not self._devices.save_config():
                return False
            logger.info("Target app set to %s", package)
            self.target_app_changed.emit(package)
        return True

    # ------------------------------------------------------------ operations
    def load_packages(self, include_system: bool = False) -> bool:
        serial = self._online_serial("Load apps")
        if not serial:
            return False
        client = self._devices.make_client()

        def on_ok(pkgs: list[str]) -> None:
            self._packages[serial] = pkgs
            self.packages_loaded.emit(serial, pkgs)
            logger.info("Loaded %d packages from %s", len(pkgs), serial)

        self._run("Load apps", app_launcher.list_packages, client, serial, include_system, on_result=on_ok)
        return True

    def launch_target(self) -> bool:
        serial = self._online_serial("Launch app")
        package = self._target_or_fail("Launch app")
        if not serial or not package:
            return False
        client = self._devices.make_client()

        def on_ok(result: LaunchResult) -> None:
            self.launch_finished.emit(result)
            self.process_state_changed.emit(serial, package, result.process_state)
            if result.command_accepted and result.process_state is ProcessState.RUNNING:
                self.operation_succeeded.emit("Launch app", result.message)
            else:
                self.operation_failed.emit("Launch app", result.message)

        self._run("Launch app", app_launcher.launch_app, client, serial, package, on_result=on_ok)
        return True

    def check_target_running(self) -> bool:
        serial = self._online_serial("Check app")
        package = self._target_or_fail("Check app")
        if not serial or not package:
            return False
        client = self._devices.make_client()

        def on_ok(state: ProcessState) -> None:
            self.process_state_changed.emit(serial, package, state)

        self._run("Check app", app_launcher.process_state, client, serial, package, on_result=on_ok)
        return True

    def stop_target(self) -> bool:
        serial = self._online_serial("Stop app")
        package = self._target_or_fail("Stop app")
        if not serial or not package:
            return False
        client = self._devices.make_client()

        def work() -> ProcessState:
            app_launcher.force_stop(client, serial, package)
            return app_launcher.process_state(client, serial, package)

        def on_ok(state: ProcessState) -> None:
            self.process_state_changed.emit(serial, package, state)
            if state is ProcessState.NOT_RUNNING:
                self.operation_succeeded.emit("Stop app", f"{package} stopped.")
            else:
                self.operation_failed.emit("Stop app", f"Stop command sent, but process state is: {state.value}.")

        self._run("Stop app", work, on_result=on_ok)
        return True

    # --------------------------------------------------------------- helpers
    def _online_serial(self, op: str) -> str | None:
        device = self._devices.selected_device
        if device is None or not device.is_online:
            self.operation_failed.emit(op, "Select an online device in Emulator Manager first.")
            return None
        return device.serial

    def _target_or_fail(self, op: str) -> str | None:
        if not self.target_package:
            self.operation_failed.emit(op, "No target app set. Load apps and choose one first.")
            return None
        return self.target_package

    def _run(self, name: str, fn: Callable, *args: object, on_result: Callable) -> None:
        self._busy += 1
        if self._busy == 1:
            self.busy_changed.emit(True)

        def on_error(exc: Exception) -> None:
            logger.error("%s failed: %s", name, exc)
            self.operation_failed.emit(name, str(exc))

        def on_done() -> None:
            self._busy = max(0, self._busy - 1)
            if self._busy == 0:
                self.busy_changed.emit(False)

        self._runner.submit(fn, *args, on_result=on_result, on_error=on_error, on_finished=on_done, name=name)
