"""Executes automation actions on a real device through ADB and the UiDriver."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from app.automation.engine import ActionOutcome
from app.automation.models import Action, ActionStatus, ActionType, Profile, validate_profile
from app.emulator import app_launcher
from app.emulator.adb_client import AdbClient, AdbError
from app.emulator.app_launcher import ProcessState
from app.emulator.reconnect import is_tcp_address
from app.pgsharp.layout import PgsharpLayout
from app.pgsharp.ui_driver import Cancelled, Outcome, UiDriver
from app.screen.mirror_controller import screenshots_dir

logger = logging.getLogger(__name__)

_OUTCOME = {Outcome.SUCCESS: ActionStatus.SUCCEEDED, Outcome.FAILED: ActionStatus.FAILED,
            Outcome.UNKNOWN: ActionStatus.UNKNOWN}
_UI_TYPES = {ActionType.TAP, ActionType.SWIPE, ActionType.OPEN_SCREEN, ActionType.SELECT_FEATURE,
             ActionType.TOGGLE_FEATURE, ActionType.WAIT_FOR_STATE}


class DeviceExecutor:
    def __init__(
        self,
        client: AdbClient,
        serial: str,
        layout: PgsharpLayout,
        target_package: str = "",
        step_delay_s: float = 0.8,
    ) -> None:
        self.client = client
        self.serial = serial
        self.layout = layout
        self.target_package = target_package
        self.step_delay_s = step_delay_s
        self._cancel = threading.Event()
        self.driver = UiDriver(client, serial, layout, sleep=self._sleep, step_delay_s=step_delay_s)

    def _sleep(self, seconds: float) -> None:
        if self._cancel.wait(seconds):
            raise Cancelled()

    # --------------------------------------------------------------- checks
    def preflight(self, profile: Profile) -> list[str]:
        problems = validate_profile(profile, self.layout)
        state = self.client.get_state(self.serial)
        if state != "device":
            problems.append(f"Device {self.serial} is '{state}', not online.")
            return problems
        if any(a.type is ActionType.LAUNCH_APP and not a.params.get("package") for a in profile.actions) \
                and not self.target_package:
            problems.append("A LAUNCH_APP action uses the target app, but no target app is set.")
        uses_ui = any(a.type in _UI_TYPES or a.expected_state for a in profile.actions)
        if uses_ui and (warning := self.driver.resolution_warning()):
            problems.append(warning)
        return problems

    def check_connection(self) -> bool:
        try:
            return self.client.get_state(self.serial) == "device"
        except AdbError:
            return False

    def recover(self, timeout_s: float, cancel: threading.Event) -> bool:
        waited = 0.0
        while waited < timeout_s and not cancel.is_set():
            if is_tcp_address(self.serial):
                try:
                    self.client.connect(self.serial)
                except (AdbError, ValueError) as exc:
                    logger.debug("Reconnect attempt failed: %s", exc)
            if self.check_connection():
                return True
            cancel.wait(2.0)
            waited += 2.0
        return False

    # -------------------------------------------------------------- execute
    def execute(self, action: Action, cancel: threading.Event) -> ActionOutcome:
        self._cancel = cancel
        p = action.params
        t = action.type
        if t is ActionType.WAIT:
            self._sleep(float(p["seconds"]))
            return ActionOutcome(ActionStatus.SUCCEEDED, f"Waited {p['seconds']} s.")
        if t is ActionType.LAUNCH_APP:
            return self._launch(p.get("package") or self.target_package, action.timeout_s)
        if t is ActionType.SCREENSHOT:
            img = self.driver.screenshot()
            label = "".join(c for c in str(p.get("label", "")) if c.isalnum() or c in "-_")[:40]
            path = screenshots_dir() / f"session_{datetime.now():%Y%m%d_%H%M%S_%f}{('_' + label) if label else ''}.png"
            if not img.save(str(path), "PNG"):
                return ActionOutcome(ActionStatus.FAILED, f"Could not write {path}")
            return ActionOutcome(ActionStatus.SUCCEEDED, f"Saved {path.name}")
        if t is ActionType.TAP:
            if p.get("element"):
                self.driver.tap_element(p["element"])
            else:
                self.driver.tap_norm(float(p["x"]), float(p["y"]))
            return ActionOutcome(ActionStatus.UNKNOWN, "Tap sent (screen effect not verified).")
        if t is ActionType.SWIPE:
            self.driver.swipe_norm(p["x1"], p["y1"], p["x2"], p["y2"], int(p.get("duration_ms", 300)))
            return ActionOutcome(ActionStatus.UNKNOWN, "Swipe sent (screen effect not verified).")
        if t is ActionType.PRESS_BACK:
            self.driver.back()
            return ActionOutcome(ActionStatus.UNKNOWN, "BACK sent (screen effect not verified).")
        if t is ActionType.OPEN_SCREEN:
            steps = [s.strip() for s in str(p["steps"]).split(",") if s.strip()]
            for step in steps:
                self.driver.tap_element(step)
                self._sleep(self.step_delay_s)
            return ActionOutcome(ActionStatus.UNKNOWN, f"Tapped {', '.join(steps)} (use an expected state to verify).")
        if t is ActionType.SELECT_FEATURE:
            r = self.driver.open_feature(p["feature"], cancel)
            return ActionOutcome(_OUTCOME[r.outcome], r.message)
        if t is ActionType.TOGGLE_FEATURE:
            r = self.driver.toggle_feature(p["feature"])
            return ActionOutcome(_OUTCOME[r.outcome], r.message)
        if t is ActionType.WAIT_FOR_STATE:
            return self.verify_expected(p["state"], action.timeout_s, cancel, float(p.get("poll_s", 1.0)))
        return ActionOutcome(ActionStatus.FAILED, f"{t.value} is handled by the engine, not the executor.")

    def verify_expected(
        self, state_id: str, timeout_s: float, cancel: threading.Event, poll_s: float = 1.0
    ) -> ActionOutcome:
        self._cancel = cancel
        m = self.driver.wait_for_state(state_id, timeout_s, poll_s, cancel)
        if m.matched is None:
            return ActionOutcome(ActionStatus.UNKNOWN, f"State '{m.name}' has no regions; cannot verify.")
        if m.matched:
            return ActionOutcome(ActionStatus.SUCCEEDED, f"Verified '{m.name}' (diff {m.score:.3f}).")
        return ActionOutcome(ActionStatus.FAILED, f"'{m.name}' not detected within {timeout_s:.0f}s (diff {m.score:.3f}).")

    def _launch(self, package: str, timeout_s: float) -> ActionOutcome:
        if not package:
            return ActionOutcome(ActionStatus.FAILED, "No package and no target app set.")
        r = app_launcher.launch_app(
            self.client, self.serial, package, verify_timeout_s=max(1.0, timeout_s - 2), sleep=self._sleep
        )
        if not r.command_accepted or r.process_state is ProcessState.NOT_RUNNING:
            return ActionOutcome(ActionStatus.FAILED, r.message)
        status = ActionStatus.SUCCEEDED if r.process_state is ProcessState.RUNNING else ActionStatus.UNKNOWN
        return ActionOutcome(status, r.message)
