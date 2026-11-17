"""Scriptable Executor for engine tests."""

from __future__ import annotations

import threading
import time

from app.automation.engine import ActionOutcome
from app.automation.models import Action, ActionStatus, ActionType, Profile
from app.emulator.adb_client import AdbCommandError


class FakeExecutor:
    def __init__(self) -> None:
        self.preflight_errors: list[str] = []
        self.results: dict[str, list[ActionOutcome | Exception]] = {}  # uid -> queue
        self.default = ActionOutcome(ActionStatus.SUCCEEDED, "ok")
        self.executed: list[str] = []
        self.verify_result = ActionOutcome(ActionStatus.SUCCEEDED, "verified")
        self.connected = True
        self.recovers = False
        self.recover_calls = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()
        self.on_execute = None  # optional hook(action)

    def preflight(self, profile: Profile) -> list[str]:
        return list(self.preflight_errors)

    def execute(self, action: Action, cancel: threading.Event) -> ActionOutcome:
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            self.executed.append(action.uid)
            if self.on_execute:
                self.on_execute(action)
            if action.type is ActionType.WAIT:
                if cancel.wait(float(action.params["seconds"])):
                    from app.pgsharp.ui_driver import Cancelled

                    raise Cancelled()
            queue = self.results.get(action.uid)
            if queue:
                r = queue.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r
            return self.default
        finally:
            with self._lock:
                self.concurrent -= 1

    def verify_expected(self, state_id, timeout_s, cancel) -> ActionOutcome:
        return self.verify_result

    def check_connection(self) -> bool:
        return self.connected

    def recover(self, timeout_s, cancel) -> bool:
        self.recover_calls += 1
        if self.recovers:
            self.connected = True
        return self.recovers


def disconnect_error() -> AdbCommandError:
    return AdbCommandError("adb: device 'emulator-5554' not found")


def wait_until(pred, timeout=3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()
