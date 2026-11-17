"""Coordinates ADB operations, device list state and device selection.

This is a non-visual QObject: the UI observes its signals and calls its
methods; all blocking ADB work runs on the :class:`TaskRunner` thread pool.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QObject, QTimer, Signal

from app.core.config import AppConfig, ConfigManager
from app.core.task_runner import TaskRunner
from app.emulator import bluestacks
from app.emulator.adb_client import (
    AdbClient,
    AdbNotConfiguredError,
    AdbNotFoundError,
    AdbTimeoutError,
)
from app.emulator.adb_locator import AdbLocation, locate_adb, verify_adb
from app.emulator.emulator_launcher import join_args, launch_command, launch_emulator
from app.emulator.instances import DiscoveryResult, EmulatorInstance
from app.emulator.models import AdbDevice, DeviceInfo
from app.emulator.reconnect import ReconnectAction, is_tcp_address, plan_reconnect
from app.emulator.selection import choose_selected_serial

logger = logging.getLogger(__name__)

ClientFactory = Callable[[str, float], AdbClient]


class AdbStatus(StrEnum):
    UNKNOWN = "Not checked"
    NOT_CONFIGURED = "Not configured"
    NOT_FOUND = "Not found"
    TIMEOUT = "Timed out"
    ERROR = "Error"
    OK = "Connected"


def _default_client_factory(path: str, timeout: float) -> AdbClient:
    return AdbClient(path, timeout=timeout)


class DeviceController(QObject):
    devices_changed = Signal(list)  # list[AdbDevice]
    selected_device_changed = Signal(object)  # str | None (serial)
    adb_status_changed = Signal(object, str)  # AdbStatus, message
    device_info_ready = Signal(object)  # DeviceInfo
    operation_started = Signal(str)  # operation name
    operation_succeeded = Signal(str, str)  # operation, message
    operation_failed = Signal(str, str)  # operation, message
    busy_changed = Signal(bool)
    adb_path_changed = Signal(str)
    instances_discovered = Signal(object)  # DiscoveryResult
    reconnect_attempted = Signal(str, bool)  # address, success

    def __init__(
        self,
        config_manager: ConfigManager,
        config: AppConfig,
        runner: TaskRunner,
        client_factory: ClientFactory | None = None,
        locator: Callable[[str | None], AdbLocation | None] | None = None,
        verifier: Callable[[str], str] | None = None,
        discoverer: Callable[[str], DiscoveryResult] | None = None,
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self._config = config
        self._runner = runner
        self._client_factory = client_factory or _default_client_factory
        self._locate = locator or (lambda configured: locate_adb(configured))
        self._verify = verifier or verify_adb
        self._discover = discoverer or (lambda conf: bluestacks.discover(conf))
        self._clock = clock
        self._last_reconnect: dict[str, float] = {}
        self._reconnect_in_flight = False
        self._reconnect_failures: dict[str, int] = {}
        self._devices: list[AdbDevice] = []
        self._selected: str | None = None
        self._status = AdbStatus.UNKNOWN
        self._status_message = ""
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._busy_ops = 0
        self._last_info: DeviceInfo | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_devices)

    # ------------------------------------------------------------ properties
    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def devices(self) -> list[AdbDevice]:
        return list(self._devices)

    @property
    def selected_serial(self) -> str | None:
        return self._selected

    @property
    def selected_device(self) -> AdbDevice | None:
        return next((d for d in self._devices if d.serial == self._selected), None)

    @property
    def adb_status(self) -> tuple[AdbStatus, str]:
        return self._status, self._status_message

    @property
    def is_busy(self) -> bool:
        return self._busy_ops > 0

    @property
    def last_device_info(self) -> DeviceInfo | None:
        return self._last_info

    # ------------------------------------------------------------ auto refresh
    def apply_refresh_settings(self) -> None:
        if self._config.auto_refresh_enabled:
            self._timer.start(int(self._config.auto_refresh_interval_s * 1000))
        else:
            self._timer.stop()

    def shutdown(self) -> None:
        self._timer.stop()

    # ---------------------------------------------------------------- config
    def set_adb_path(self, path: str) -> None:
        path = path.strip()
        if path == self._config.adb_path:
            return
        self._config.adb_path = path
        self._save_config()
        self.adb_path_changed.emit(path)
        self._set_status(AdbStatus.UNKNOWN, "ADB path changed")
        logger.info("ADB path set to %s", path or "<empty>")

    def save_config(self) -> bool:
        """Persist the shared configuration. Emits operation_failed and returns False on error."""
        try:
            self._config_manager.save(self._config)
        except OSError as exc:
            logger.error("Failed to save configuration: %s", exc)
            self.operation_failed.emit("Save settings", f"Could not save configuration: {exc}")
            return False
        return True

    _save_config = save_config

    def make_client(self) -> AdbClient:
        """A new client bound to the current ADB settings (safe to use on a worker thread)."""
        return self._client()

    def _client(self) -> AdbClient:
        return self._client_factory(self._config.adb_path, self._config.adb_command_timeout_s)

    # ------------------------------------------------------------ operations
    def refresh_devices(self) -> bool:
        """Start a background device scan. Returns False if not started now.

        A request made while a scan is running is queued and runs once that scan
        finishes, so state changes (e.g. a reconnect) are never missed.
        """
        if self._refresh_in_flight:
            self._refresh_pending = True
            return False
        if not self._config.adb_path:
            self._set_status(AdbStatus.NOT_CONFIGURED, "Set the ADB path in Settings or use Auto-detect.")
            self._update_devices([])
            return False
        self._refresh_in_flight = True
        client = self._client()
        self._begin()
        self._runner.submit(
            client.list_devices,
            on_result=self._on_devices,
            on_error=self._on_adb_error,
            on_finished=self._on_refresh_finished,
            name="list_devices",
        )
        return True

    def select_device(self, serial: str | None, persist: bool = True) -> None:
        """Select a device. ``persist`` saves it as the preferred device for future sessions."""
        serial = serial or None
        if serial == self._selected:
            return
        self._selected = serial
        self._last_info = None
        if serial and persist:
            self._config.preferred_device_serial = serial
            self._save_config()
            logger.info("Selected device %s", serial)
        self.selected_device_changed.emit(serial)

    def fetch_device_info(self, serial: str | None = None) -> bool:
        serial = serial or self._selected
        if not serial:
            self.operation_failed.emit("Device info", "No device selected.")
            return False
        device = next((d for d in self._devices if d.serial == serial), None)
        if device is not None and not device.is_online:
            self.operation_failed.emit(
                "Device info", f"Device {serial} is '{device.raw_state}', not online."
            )
            return False
        self._run_op("Device info", self._client().get_device_info, serial, on_result=self._on_info)
        return True

    def connect_address(self, address: str) -> None:
        def on_ok(message: str) -> None:
            self._config.remember_address(address)
            self._save_config()
            self.operation_succeeded.emit("Connect", message)
            self.refresh_devices()

        self._run_op("Connect", self._client().connect, address, on_result=on_ok)

    def restart_adb_server(self) -> None:
        def on_ok(_: object) -> None:
            self.operation_succeeded.emit("Restart ADB", "ADB server restarted.")
            self.refresh_devices()

        self._run_op("Restart ADB", self._client().restart_server, on_result=on_ok)

    def test_adb(self, path: str | None = None) -> None:
        target = (path if path is not None else self._config.adb_path).strip()

        def on_ok(version: str) -> None:
            self.operation_succeeded.emit("Test ADB", f"ADB {version} at {target}")
            if target == self._config.adb_path:
                self._set_status(AdbStatus.OK, f"ADB {version}")

        if not target:
            self.operation_failed.emit("Test ADB", "No ADB path entered.")
            return
        self._run_op("Test ADB", self._verify, target, on_result=on_ok)

    def auto_detect_adb(self) -> None:
        def on_ok(location: AdbLocation | None) -> None:
            if location is None:
                self.operation_failed.emit(
                    "Auto-detect ADB",
                    "No working ADB found. Install Android SDK Platform-Tools or browse to "
                    "your emulator's adb executable.",
                )
                return
            self.set_adb_path(location.path)
            self.operation_succeeded.emit(
                "Auto-detect ADB", f"Found ADB {location.version} ({location.source}): {location.path}"
            )
            self.refresh_devices()

        self._run_op("Auto-detect ADB", self._locate, self._config.adb_path or None, on_result=on_ok)

    def launch_emulator(self) -> None:
        def on_ok(pid: int) -> None:
            self.operation_succeeded.emit(
                "Launch emulator",
                f"Emulator process started (pid {pid}). It may take a minute to appear in ADB.",
            )

        self._run_op(
            "Launch emulator",
            launch_emulator,
            self._config.emulator_path,
            self._config.emulator_args,
            on_result=on_ok,
        )

    # ------------------------------------------------------------- reconnect
    def reconnect_selected(self) -> bool:
        """Manually reconnect the selected (or preferred) TCP device."""
        target = self._selected or self._config.preferred_device_serial or None
        if not is_tcp_address(target):
            self.operation_failed.emit(
                "Reconnect", "Only TCP/IP devices (host:port) can be reconnected. USB/console devices reconnect on their own."
            )
            return False
        device = next((d for d in self._devices if d.serial == target), None)
        action = ReconnectAction(target, disconnect_first=device is not None)
        return self._start_reconnect(action, manual=True)

    def _maybe_reconnect(self) -> None:
        if self._reconnect_in_flight:
            return
        target = self._selected or self._config.preferred_device_serial or None
        action = plan_reconnect(
            self._devices,
            self._selected,
            self._config.preferred_device_serial or None,
            self._last_reconnect.get(target or ""),
            self._clock(),
        )
        if action:
            self._start_reconnect(action, manual=False)

    def _start_reconnect(self, action: ReconnectAction, manual: bool) -> bool:
        if self._reconnect_in_flight:
            return False
        self._reconnect_in_flight = True
        self._last_reconnect[action.address] = self._clock()
        client = self._client()

        def work() -> str:
            if action.disconnect_first:
                try:
                    client.disconnect(action.address)
                except Exception as exc:  # noqa: BLE001 - stale entry may already be gone
                    logger.debug("disconnect %s before reconnect: %s", action.address, exc)
            return client.connect(action.address)

        def on_ok(message: str) -> None:
            self._reconnect_failures.pop(action.address, None)
            logger.info("Reconnected %s: %s", action.address, message)
            self.reconnect_attempted.emit(action.address, True)
            if manual:
                self.operation_succeeded.emit("Reconnect", message)
            self.refresh_devices()

        def on_err(exc: Exception) -> None:
            n = self._reconnect_failures.get(action.address, 0) + 1
            self._reconnect_failures[action.address] = n
            # Log the first failure of a streak at WARNING, the rest at DEBUG to avoid log spam.
            (logger.warning if n == 1 or manual else logger.debug)("Reconnect to %s failed: %s", action.address, exc)
            self.reconnect_attempted.emit(action.address, False)
            if manual:
                self.operation_failed.emit("Reconnect", str(exc))

        def on_done() -> None:
            self._reconnect_in_flight = False
            self._end()

        self._begin()
        self._runner.submit(work, on_result=on_ok, on_error=on_err, on_finished=on_done, name="reconnect")
        return True

    # ------------------------------------------------------------- instances
    def discover_instances(self) -> None:
        def on_ok(result: DiscoveryResult) -> None:
            self.instances_discovered.emit(result)

        self._run_op("Discover instances", self._discover, self._config.bluestacks_conf_path, on_result=on_ok)

    def connect_instance(self, instance: EmulatorInstance) -> None:
        if not instance.adb_address:
            self.operation_failed.emit("Connect", f"No ADB port is known for {instance.display_name}.")
            return
        self.connect_address(instance.adb_address)

    def launch_instance(self, instance: EmulatorInstance) -> None:
        if not instance.launch_executable:
            self.operation_failed.emit(
                "Launch emulator", f"The launcher for {instance.provider} was not found. Set it in Settings."
            )
            return
        cmd = [instance.launch_executable, *instance.launch_args]

        def on_ok(pid: int) -> None:
            self.operation_succeeded.emit(
                "Launch emulator", f"Started {instance.display_name} (pid {pid}). It may take a minute to boot."
            )

        self._run_op("Launch emulator", launch_command, cmd, on_result=on_ok)

    def use_instance_as_launcher(self, instance: EmulatorInstance) -> None:
        if not instance.launch_executable:
            self.operation_failed.emit("Use as launcher", "No launcher executable is known for this instance.")
            return
        self._config.emulator_path = instance.launch_executable
        self._config.emulator_args = join_args(list(instance.launch_args))
        if instance.adb_address:
            self._config.preferred_device_serial = instance.adb_address
        self._save_config()
        self.operation_succeeded.emit(
            "Use as launcher", f"{instance.display_name} is now the default emulator and preferred device."
        )

    # --------------------------------------------------------------- helpers
    def _run_op(self, name: str, fn: Callable, *args: object, on_result: Callable) -> None:
        self._begin()
        self.operation_started.emit(name)

        def on_error(exc: Exception) -> None:
            logger.error("%s failed: %s", name, exc)
            self.operation_failed.emit(name, str(exc))
            if isinstance(exc, (AdbNotFoundError, AdbNotConfiguredError)):
                self._on_adb_error(exc)

        self._runner.submit(fn, *args, on_result=on_result, on_error=on_error, on_finished=self._end, name=name)

    def _begin(self) -> None:
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.busy_changed.emit(True)

    def _end(self) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.busy_changed.emit(False)

    def _on_refresh_finished(self) -> None:
        self._refresh_in_flight = False
        self._end()
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh_devices)

    def _on_devices(self, devices: list[AdbDevice]) -> None:
        online = sum(1 for d in devices if d.is_online)
        self._set_status(AdbStatus.OK, f"{len(devices)} device(s), {online} online")
        self._update_devices(devices)
        if self._config.auto_reconnect_enabled:
            self._maybe_reconnect()

    def _on_info(self, info: DeviceInfo) -> None:
        if info.serial != self._selected:
            return  # selection changed while the request was running
        self._last_info = info
        self.device_info_ready.emit(info)

    def _on_adb_error(self, exc: Exception) -> None:
        if isinstance(exc, AdbNotConfiguredError):
            status = AdbStatus.NOT_CONFIGURED
        elif isinstance(exc, AdbNotFoundError):
            status = AdbStatus.NOT_FOUND
        elif isinstance(exc, AdbTimeoutError):
            status = AdbStatus.TIMEOUT
        else:
            status = AdbStatus.ERROR
        self._set_status(status, str(exc))
        # Device state is unknown when ADB fails - do not keep showing stale devices.
        self._update_devices([])

    def _update_devices(self, devices: list[AdbDevice]) -> None:
        if devices != self._devices:
            self._log_device_diff(self._devices, devices)
            self._devices = list(devices)
            self.devices_changed.emit(self.devices)
        new_sel = choose_selected_serial(
            self._devices, self._selected, self._config.preferred_device_serial or None
        )
        if new_sel != self._selected:
            # An automatic choice must not overwrite a device the user explicitly preferred.
            self.select_device(new_sel, persist=not self._config.preferred_device_serial)

    @staticmethod
    def _log_device_diff(old: list[AdbDevice], new: list[AdbDevice]) -> None:
        old_map = {d.serial: d.raw_state for d in old}
        new_map = {d.serial: d.raw_state for d in new}
        for serial, state in new_map.items():
            if serial not in old_map:
                logger.info("Device detected: %s (%s)", serial, state)
            elif old_map[serial] != state:
                logger.info("Device %s changed state: %s -> %s", serial, old_map[serial], state)
        for serial in old_map.keys() - new_map.keys():
            logger.info("Device disconnected: %s", serial)

    def _set_status(self, status: AdbStatus, message: str) -> None:
        if (status, message) == (self._status, self._status_message):
            return
        if status not in (AdbStatus.OK, AdbStatus.UNKNOWN) and status != self._status:
            logger.warning("ADB status: %s - %s", status.value, message)
        self._status = status
        self._status_message = message
        self.adb_status_changed.emit(status, message)
