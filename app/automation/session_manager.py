"""Qt-facing owner of the (single) active automation session."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from app.automation.engine import AutomationSession, SessionListener, SessionSummary
from app.automation.executor import DeviceExecutor
from app.automation.models import Action, Profile
from app.automation.repository import ProfileError, ProfileRepository
from app.automation.state_machine import ACTIVE, SessionState
from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository
from app.pgsharp.controller import PgsharpController
from app.pgsharp.layout import PgsharpLayout

logger = logging.getLogger(__name__)


class SessionManager(QObject):
    state_changed = Signal(object)  # SessionState
    action_updated = Signal(int, object)  # index, Action (copy)
    session_log = Signal(str, str)  # level, message
    confirmation_requested = Signal(str)
    session_started = Signal(object)  # Profile
    session_finished = Signal(object)  # SessionSummary
    current_profile_changed = Signal(object)  # int | None
    operation_failed = Signal(str, str)

    def __init__(
        self,
        devices: DeviceController,
        apps: AppController,
        pgsharp: PgsharpController,
        profiles: ProfileRepository,
        history: SessionHistoryRepository | None = None,
        logs: ActivityLogRepository | None = None,
        executor_factory=None,  # noqa: ANN001 - (client, serial, layout, package) -> Executor, for tests
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._devices = devices
        self._apps = apps
        self._pg = pgsharp
        self.profiles = profiles
        self._history = history
        self._logs = logs
        self._executor_factory = executor_factory or (
            lambda client, serial, layout, pkg: DeviceExecutor(client, serial, layout, pkg)
        )
        self._session: AutomationSession | None = None
        self._thread: threading.Thread | None = None
        self._session_id: int | None = None
        self._serial: str | None = None
        self._start_lock = threading.Lock()
        self.started_at: datetime | None = None
        self.current_action: str = ""
        self.last_error: str = ""
        self.last_summary: SessionSummary | None = None
        devices.selected_device_changed.connect(self._on_device_changed)

    # ------------------------------------------------------------ properties
    @property
    def state(self) -> SessionState:
        return self._session.state if self._session else SessionState.IDLE

    @property
    def is_active(self) -> bool:
        return self._session is not None and (self._thread is not None and self._thread.is_alive())

    @property
    def current_profile_id(self) -> int | None:
        pid = self._devices.config.current_profile_id
        return pid or None

    @property
    def session_id(self) -> int | None:
        return self._session_id if self.is_active else None

    def set_current_profile(self, profile_id: int | None) -> None:
        if (profile_id or 0) != self._devices.config.current_profile_id:
            self._devices.config.current_profile_id = profile_id or 0
            self._devices.save_config()
            self.current_profile_changed.emit(profile_id)

    def current_profile_name(self) -> str:
        pid = self.current_profile_id
        if not pid:
            return ""
        try:
            return self.profiles.get(pid).name
        except ProfileError:
            return ""

    # --------------------------------------------------------------- control
    def start(self, profile_id: int | None = None) -> bool:
        if not self._start_lock.acquire(blocking=False):
            return False
        try:
            return self._start(profile_id or self.current_profile_id)
        finally:
            self._start_lock.release()

    def _start(self, profile_id: int | None) -> bool:
        if self.is_active:
            self.operation_failed.emit("Start session", "A session is already running on this device.")
            return False
        if not profile_id:
            self.operation_failed.emit("Start session", "Select a profile in Automation Manager first.")
            return False
        device = self._devices.selected_device
        if device is None or not device.is_online:
            self.operation_failed.emit("Start session", "Select an online device first.")
            return False
        try:
            profile = self.profiles.get(profile_id)
        except ProfileError as exc:
            self.operation_failed.emit("Start session", str(exc))
            return False
        layout = PgsharpLayout.from_dict(self._pg.layout.to_dict())  # snapshot: edits don't affect a run
        executor = self._executor_factory(self._devices.make_client(), device.serial, layout, self._apps.target_package)
        listener = SessionListener(
            on_state=lambda _old, new: self.state_changed.emit(new),
            on_action=self._emit_action,
            on_log=self._on_log,
            on_confirmation=self.confirmation_requested.emit,
        )
        self._session = AutomationSession(profile, executor, listener)
        self._serial = device.serial
        self.started_at = datetime.now()
        self.current_action = ""
        self.last_error = ""
        if self._history is not None:
            self._session_id = self._history.start(profile.id, profile.name, device.serial, len(profile.actions))
        self.set_current_profile(profile.id)
        self._thread = threading.Thread(target=self._run, args=(self._session,), name="automation", daemon=True)
        self.session_started.emit(profile)
        self._thread.start()
        return True

    def _run(self, session: AutomationSession) -> None:
        summary = session.run()
        self.last_summary = summary
        self.last_error = summary.last_error
        if self._history is not None and self._session_id is not None:
            try:
                self._history.finish(
                    self._session_id, summary.result, summary.succeeded, summary.failed, summary.unknown,
                    summary.last_error,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Could not record session history")
        self.session_finished.emit(summary)

    def pause(self) -> bool:
        return bool(self._session and self.is_active and self._session.pause())

    def resume(self) -> bool:
        return bool(self._session and self.is_active and self._session.resume())

    def stop(self) -> bool:
        return bool(self._session and self.is_active and self._session.stop())

    def emergency_stop(self) -> None:
        if self._session and self.is_active:
            self._session.emergency_stop()

    def respond_confirmation(self, answer: bool) -> None:
        if self._session:
            self._session.respond_confirmation(answer)

    def wait(self, timeout_s: float = 10.0) -> bool:
        if self._thread is not None:
            self._thread.join(timeout_s)
            return not self._thread.is_alive()
        return True

    def shutdown(self) -> None:
        if self.is_active:
            logger.warning("Application closing: emergency-stopping the automation session.")
            self.emergency_stop()
            self.wait(10)

    # --------------------------------------------------------------- helpers
    def _emit_action(self, index: int, action: Action) -> None:
        self.current_action = f"{index + 1}. {action.type.value} {action.summary()} - {action.status.value}"
        copy = Action.from_dict(action.to_dict())
        copy.uid, copy.status = action.uid, action.status
        self.action_updated.emit(index, copy)

    def _on_log(self, level: str, message: str) -> None:
        if level == "ERROR":
            self.last_error = message
        if self._logs is not None:
            try:
                self._logs.add(level, "automation", message, self._session_id)
            except Exception:  # noqa: BLE001
                logger.debug("activity log write failed", exc_info=True)
        self.session_log.emit(level, message)

    def _on_device_changed(self, serial: object) -> None:
        if self.is_active and serial != self._serial and self._session and self._session.state in ACTIVE:
            logger.warning("Selected device changed during a session; stopping the session.")
            self._session.stop()

    def load_profile(self, profile_id: int) -> Profile:
        return self.profiles.get(profile_id)
