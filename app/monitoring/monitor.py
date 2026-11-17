"""Aggregated, periodically refreshed session/status snapshot for the Activity Monitor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from app.automation.models import Action, ActionStatus, ActionType
from app.automation.session_manager import SessionManager
from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.emulator import app_launcher
from app.emulator.adb_client import AdbError
from app.emulator.app_launcher import ProcessState
from app.pgsharp.controller import PgsharpController
from app.screen.mirror_controller import MirrorController

logger = logging.getLogger(__name__)

POKEMON_GO_PACKAGE = "com.nianticlabs.pokemongo"
POLL_INTERVAL_MS = 15_000
_VERIFYING = {ActionType.WAIT_FOR_STATE, ActionType.SELECT_FEATURE, ActionType.TOGGLE_FEATURE}


@dataclass
class StatusSnapshot:
    adb: str = "Not checked"
    emulator: str = "No device selected"
    pgsharp: str = "Not checked"
    pokemon_go: str = "Not checked"
    scrcpy: str = "Not running"
    profile: str = "none"
    session_state: str = "IDLE"
    current_action: str = "-"
    session_started: datetime | None = None
    last_verification: str = "none"
    last_error: str = "none"
    updated: datetime = field(default_factory=datetime.now)


class StatusMonitor(QObject):
    changed = Signal(object)  # StatusSnapshot

    def __init__(
        self,
        devices: DeviceController,
        apps: AppController,
        mirror: MirrorController,
        pgsharp: PgsharpController,
        sessions: SessionManager,
        runner: TaskRunner,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._d, self._apps, self._m, self._pg, self._s, self._runner = devices, apps, mirror, pgsharp, sessions, runner
        self.snapshot = StatusSnapshot()
        self._polling = False
        self._last_verified: tuple[datetime, str] | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll_apps)

        devices.adb_status_changed.connect(lambda *_: self.refresh())
        devices.devices_changed.connect(lambda *_: self.refresh())
        devices.selected_device_changed.connect(lambda *_: self._reset_apps())
        mirror.state_changed.connect(lambda *_: self.refresh())
        pgsharp.verification_done.connect(lambda *_: self.refresh())
        pgsharp.feature_tested.connect(lambda *_: self.refresh())
        apps.process_state_changed.connect(self._on_target_state)
        for sig in (sessions.state_changed, sessions.session_finished, sessions.current_profile_changed,
                    sessions.session_started):
            sig.connect(lambda *_: self.refresh())
        sessions.action_updated.connect(self._on_action)
        self.refresh()

    def start(self, interval_ms: int = POLL_INTERVAL_MS) -> None:
        self._timer.start(interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def note_error(self, message: str) -> None:
        self.snapshot.last_error = f"{datetime.now():%H:%M:%S} {message}"
        self.changed.emit(self.snapshot)

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        s = self.snapshot
        status, msg = self._d.adb_status
        s.adb = status.value + (f" - {msg}" if msg else "")
        serial = self._d.selected_serial
        dev = self._d.selected_device
        if not serial:
            s.emulator = "No device selected"
        elif dev is None:
            s.emulator = f"{serial}: disconnected"
        else:
            s.emulator = f"{dev.display_name}: {dev.raw_state}"
        s.scrcpy = self._m.state.value + (f" - {self._m.detail}" if self._m.detail else "")
        s.profile = self._s.current_profile_name() or "none"
        s.session_state = self._s.state.value
        s.current_action = self._s.current_action or "-" if self._s.is_active else "-"
        s.session_started = self._s.started_at if self._s.is_active else None
        candidates = [c for c in (self._pg.last_verified, self._last_verified) if c]
        if candidates:
            when, what = max(candidates, key=lambda c: c[0])
            s.last_verification = f"{what} at {when:%H:%M:%S}"
        if self._s.last_error:
            s.last_error = self._s.last_error
        s.updated = datetime.now()
        self.changed.emit(s)

    def _reset_apps(self) -> None:
        self.snapshot.pgsharp = "Not checked"
        self.snapshot.pokemon_go = "Not checked"
        self.refresh()

    def _on_target_state(self, serial: str, package: str, state: ProcessState) -> None:
        if package == self._apps.target_package and serial == self._d.selected_serial:
            self.snapshot.pgsharp = f"{state.value} ({package})"
            self.refresh()

    def _on_action(self, _index: int, action: Action) -> None:
        if action.status is ActionStatus.SUCCEEDED and (action.expected_state or action.type in _VERIFYING):
            self._last_verified = (datetime.now(), f"{action.type.value} {action.summary()}".strip())
        self.refresh()

    # ------------------------------------------------------------------ poll
    def poll_apps(self) -> bool:
        """Check PGSharp and Pokémon GO process state in the background (only with an online device)."""
        dev = self._d.selected_device
        if self._polling or dev is None or not dev.is_online:
            return False
        self._polling = True
        client = self._d.make_client()
        serial = dev.serial
        target = self._apps.target_package

        def work() -> tuple[str | None, str]:
            pg = None
            if target:
                pg = f"{app_launcher.process_state(client, serial, target).value} ({target})"
            if target == POKEMON_GO_PACKAGE:
                go = "Same package as the target app"
            elif app_launcher.is_installed(client, serial, POKEMON_GO_PACKAGE):
                go = app_launcher.process_state(client, serial, POKEMON_GO_PACKAGE).value
            else:
                go = "Not installed (or not detectable)"
            return pg, go

        def on_ok(result: tuple[str | None, str]) -> None:
            if serial != self._d.selected_serial:
                return
            pg, go = result
            self.snapshot.pgsharp = pg or "No target app set"
            self.snapshot.pokemon_go = go
            self.refresh()

        def on_err(exc: Exception) -> None:
            if isinstance(exc, AdbError):
                self.snapshot.pgsharp = self.snapshot.pokemon_go = "Unknown (device not responding)"
                self.refresh()

        def done() -> None:
            self._polling = False

        self._runner.submit(work, on_result=on_ok, on_error=on_err, on_finished=done, name="status_poll")
        return True
