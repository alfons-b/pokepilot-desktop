"""Runs and supervises the scrcpy process; captures screenshots.

scrcpy is driven with :class:`QProcess`, which is asynchronous and never blocks
the GUI thread. Mouse and keyboard control happen inside the scrcpy window.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.paths import data_dir
from app.screen.scrcpy import ScrcpyError, ScrcpyOptions, ScrcpyVersion, build_args, locate_scrcpy, verify_scrcpy

logger = logging.getLogger(__name__)

# Output lines that prove scrcpy opened its video window.
_READY_PATTERNS = ("texture:", "renderer:", "new texture")
_ERROR_RE = re.compile(r"^(ERROR|FATAL)\b", re.IGNORECASE)
MAX_RESTARTS = 3
RESTART_WINDOW_S = 120.0
RESTART_DELAY_MS = 2000
STOP_GRACE_MS = 3000


class MirrorState(StrEnum):
    STOPPED = "Not running"
    STARTING = "Starting"
    RUNNING = "Running"
    STOPPING = "Stopping"
    FAILED = "Failed"


def screenshots_dir() -> Path:
    path = data_dir() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", serial)


class MirrorController(QObject):
    state_changed = Signal(object, str)  # MirrorState, detail
    output_line = Signal(str)
    screenshot_saved = Signal(str)  # path
    operation_succeeded = Signal(str, str)
    operation_failed = Signal(str, str)
    scrcpy_path_changed = Signal(str)

    def __init__(self, devices: DeviceController, runner: TaskRunner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        self._runner = runner
        self._process: QProcess | None = None
        self._state = MirrorState.STOPPED
        self._detail = ""
        self._serial: str | None = None
        self._user_stop = False
        self._restarts: deque[float] = deque()
        self._version: ScrcpyVersion | None = None
        self._log: deque[str] = deque(maxlen=200)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.timeout.connect(self._assume_running)
        devices.selected_device_changed.connect(self._on_device_changed)

    # ------------------------------------------------------------ properties
    @property
    def state(self) -> MirrorState:
        return self._state

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def mirrored_serial(self) -> str | None:
        return self._serial if self._state in (MirrorState.STARTING, MirrorState.RUNNING) else None

    @property
    def output_log(self) -> list[str]:
        return list(self._log)

    def options_from_config(self) -> ScrcpyOptions:
        c = self._devices.config
        return ScrcpyOptions(
            max_size=c.scrcpy_max_size,
            max_fps=c.scrcpy_max_fps,
            bitrate_mbps=c.scrcpy_bitrate_mbps,
            fullscreen=c.scrcpy_fullscreen,
            always_on_top=c.scrcpy_always_on_top,
            stay_awake=c.scrcpy_stay_awake,
            view_only=c.scrcpy_view_only,
            uhid_keyboard=c.scrcpy_uhid_keyboard,
        )

    # ------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        if self._state in (MirrorState.STARTING, MirrorState.RUNNING, MirrorState.STOPPING):
            self.operation_failed.emit("Start mirroring", f"Mirroring is already {self._state.value.lower()}.")
            return False
        device = self._devices.selected_device
        if device is None or not device.is_online:
            self.operation_failed.emit("Start mirroring", "Select an online device first.")
            return False
        path = self._devices.config.scrcpy_path
        if not path or not Path(path).is_file():
            self.operation_failed.emit(
                "Start mirroring", "scrcpy is not configured. Set its path in Settings or use Auto-detect."
            )
            return False
        try:
            args = build_args(device.serial, self.options_from_config(), self._version)
        except ScrcpyError as exc:
            self.operation_failed.emit("Start mirroring", str(exc))
            return False
        self._user_stop = False
        self._serial = device.serial
        self._launch(path, args)
        return True

    def stop(self) -> None:
        if self._process is None or self._state in (MirrorState.STOPPED, MirrorState.FAILED):
            self._set_state(MirrorState.STOPPED, "")
            return
        self._user_stop = True
        self._set_state(MirrorState.STOPPING, "Closing scrcpy window")
        self._process.terminate()  # WM_CLOSE on Windows, SIGTERM elsewhere
        self._kill_timer.start(STOP_GRACE_MS)

    def restart(self) -> None:
        if self._process is not None and self._state in (MirrorState.STARTING, MirrorState.RUNNING):
            proc = self._process
            self.stop()
            proc.finished.connect(lambda *_: QTimer.singleShot(200, self.start))
        else:
            self.start()

    def shutdown(self) -> None:
        """Called on application exit: stop scrcpy synchronously, without further callbacks."""
        self._kill_timer.stop()
        self._ready_timer.stop()
        proc, self._process = self._process, None
        self._user_stop = True
        if proc is None:
            return
        for sig in (proc.finished, proc.errorOccurred, proc.readyReadStandardOutput):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.terminate()
            if not proc.waitForFinished(STOP_GRACE_MS):
                proc.kill()
                proc.waitForFinished(1000)
        proc.setParent(None)
        proc.deleteLater()
        self._set_state(MirrorState.STOPPED, "")

    # ------------------------------------------------------------- scrcpy path
    def detect_scrcpy(self) -> None:
        def on_ok(found: tuple[str, ScrcpyVersion] | None) -> None:
            if found is None:
                self.operation_failed.emit(
                    "Auto-detect scrcpy", "scrcpy not found. Download it from github.com/Genymobile/scrcpy/releases."
                )
                return
            path, version = found
            self._version = version
            self._devices.config.scrcpy_path = path
            self._devices.save_config()
            self.scrcpy_path_changed.emit(path)
            self.operation_succeeded.emit("Auto-detect scrcpy", f"Found scrcpy {version} at {path}")

        self._runner.submit(
            locate_scrcpy,
            self._devices.config.scrcpy_path,
            on_result=on_ok,
            on_error=lambda e: self.operation_failed.emit("Auto-detect scrcpy", str(e)),
            name="locate_scrcpy",
        )

    def test_scrcpy(self, path: str) -> None:
        def on_ok(version: ScrcpyVersion) -> None:
            if path == self._devices.config.scrcpy_path:
                self._version = version
            self.operation_succeeded.emit("Test scrcpy", f"scrcpy {version} at {path}")

        self._runner.submit(
            verify_scrcpy,
            path,
            on_result=on_ok,
            on_error=lambda e: self.operation_failed.emit("Test scrcpy", str(e)),
            name="verify_scrcpy",
        )

    # ------------------------------------------------------------ screenshot
    def capture_screenshot(self) -> bool:
        device = self._devices.selected_device
        if device is None or not device.is_online:
            self.operation_failed.emit("Screenshot", "Select an online device first.")
            return False
        client = self._devices.make_client()
        serial = device.serial

        def work() -> str:
            png = client.screencap(serial)
            path = screenshots_dir() / f"{_safe_name(serial)}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            path.write_bytes(png)
            return str(path)

        def on_ok(path: str) -> None:
            logger.info("Screenshot saved: %s", path)
            self.screenshot_saved.emit(path)
            self.operation_succeeded.emit("Screenshot", f"Saved {Path(path).name}")

        self._runner.submit(
            work,
            on_result=on_ok,
            on_error=lambda e: self.operation_failed.emit("Screenshot", str(e)),
            name="screenshot",
        )
        return True

    # -------------------------------------------------------------- internals
    def _launch(self, program: str, args: list[str]) -> None:
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        # Make scrcpy use the same adb as PokePilot, avoiding two adb server versions fighting.
        if self._devices.config.adb_path:
            env.insert("ADB", self._devices.config.adb_path)
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(str(Path(program).parent))
        proc.readyReadStandardOutput.connect(lambda p=proc: self._on_output(p))
        proc.errorOccurred.connect(lambda err, p=proc: self._on_error(p, err))
        proc.finished.connect(lambda code, status, p=proc: self._on_finished(p, code, status))
        self._process = proc
        self._log.clear()
        self._set_state(MirrorState.STARTING, f"Connecting to {self._serial}")
        logger.info("Starting scrcpy for %s: %s %s", self._serial, program, " ".join(args))
        proc.start(program, args)
        self._ready_timer.start(8000)

    def _on_output(self, proc: QProcess) -> None:
        if proc is not self._process:
            return
        text = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            self._log.append(line)
            self.output_line.emit(line)
            if _ERROR_RE.match(line):
                logger.warning("scrcpy: %s", line)
            else:
                logger.debug("scrcpy: %s", line)
            if self._state is MirrorState.STARTING and any(p in line.lower() for p in _READY_PATTERNS):
                self._ready_timer.stop()
                self._set_state(MirrorState.RUNNING, f"Mirroring {self._serial}")

    def _assume_running(self) -> None:
        # Still alive after 8 s but no recognised output: report honestly.
        if self._state is MirrorState.STARTING and self._process is not None:
            self._set_state(MirrorState.RUNNING, f"Process running for {self._serial} (window not confirmed)")

    def _on_error(self, proc: QProcess, error: QProcess.ProcessError) -> None:
        if proc is not self._process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._ready_timer.stop()
            msg = f"scrcpy failed to start: {proc.errorString()}"
            logger.error(msg)
            self._set_state(MirrorState.FAILED, msg)
            self.operation_failed.emit("Start mirroring", msg)
            self._process = None
            proc.deleteLater()

    def _on_finished(self, proc: QProcess, code: int, status: QProcess.ExitStatus) -> None:
        if proc is not self._process:
            proc.deleteLater()
            return
        self._kill_timer.stop()
        self._ready_timer.stop()
        self._process = None
        proc.deleteLater()
        if self._user_stop:
            logger.info("scrcpy stopped")
            self._set_state(MirrorState.STOPPED, "")
            return
        last_error = next((ln for ln in reversed(self._log) if _ERROR_RE.match(ln)), "")
        msg = f"scrcpy exited unexpectedly (code {code})" + (f": {last_error}" if last_error else "")
        logger.error(msg)
        self._set_state(MirrorState.FAILED, msg)
        if self._devices.config.scrcpy_auto_restart:
            self._schedule_restart()

    def _schedule_restart(self) -> None:
        now = time.monotonic()
        while self._restarts and now - self._restarts[0] > RESTART_WINDOW_S:
            self._restarts.popleft()
        if len(self._restarts) >= MAX_RESTARTS:
            msg = f"scrcpy crashed {MAX_RESTARTS} times in {RESTART_WINDOW_S:.0f}s; automatic restart disabled."
            logger.error(msg)
            self.operation_failed.emit("Mirroring", msg)
            return
        self._restarts.append(now)
        logger.info("Restarting scrcpy in %d ms (attempt %d)", RESTART_DELAY_MS, len(self._restarts))
        QTimer.singleShot(RESTART_DELAY_MS, self._restart_if_still_wanted)

    def _restart_if_still_wanted(self) -> None:
        device = self._devices.selected_device
        if self._state is MirrorState.FAILED and device is not None and device.is_online and device.serial == self._serial:
            self.start()
        else:
            logger.info("Skipping scrcpy restart: device not online or selection changed.")

    def _force_kill(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            logger.warning("scrcpy did not close in time; killing it")
            self._process.kill()

    def _on_device_changed(self, serial: object) -> None:
        if self._serial and serial != self._serial and self._state in (MirrorState.STARTING, MirrorState.RUNNING):
            logger.info("Selected device changed; stopping mirroring of %s", self._serial)
            self.stop()

    def _set_state(self, state: MirrorState, detail: str) -> None:
        if (state, detail) == (self._state, self._detail):
            return
        self._state = state
        self._detail = detail
        self.state_changed.emit(state, detail)
