"""Sequential automation engine (no Qt, runs on one worker thread).

Guarantees:
* exactly one action executes at a time (duplicate-action protection),
* every action ends as SUCCEEDED, FAILED, UNKNOWN, SKIPPED or CANCELLED - an ADB
  command that returned 0 is UNKNOWN unless an expected state was verified,
* stop finishes the current action; emergency stop interrupts waits immediately,
* if the device disconnects, recovery is attempted; otherwise pending actions are cancelled.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.automation.models import Action, ActionStatus, ActionType, ErrorPolicy, Profile
from app.automation.state_machine import SessionState, StateMachine
from app.emulator.adb_client import AdbError, AdbNotConfiguredError, AdbNotFoundError
from app.pgsharp.ui_driver import Cancelled

logger = logging.getLogger(__name__)

RETRY_DELAY_S = 1.0
RECOVER_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ActionOutcome:
    status: ActionStatus
    message: str = ""


class Executor(Protocol):
    def preflight(self, profile: Profile) -> list[str]: ...
    def execute(self, action: Action, cancel: threading.Event) -> ActionOutcome: ...
    def verify_expected(self, state_id: str, timeout_s: float, cancel: threading.Event) -> ActionOutcome: ...
    def check_connection(self) -> bool: ...
    def recover(self, timeout_s: float, cancel: threading.Event) -> bool: ...


@dataclass
class SessionListener:
    on_state: Callable[[SessionState, SessionState], None] = lambda old, new: None
    on_action: Callable[[int, Action], None] = lambda index, action: None
    on_log: Callable[[str, str], None] = lambda level, message: None
    on_confirmation: Callable[[str], None] = lambda message: None


@dataclass
class SessionSummary:
    profile_name: str
    result: str = "RUNNING"  # COMPLETED | FAILED | STOPPED | EMERGENCY_STOPPED
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    unknown: int = 0
    skipped: int = 0
    cancelled: int = 0
    last_error: str = ""


class _Abort(Exception):
    """Unrecoverable condition: end the session as FAILED."""


class AutomationSession:
    def __init__(
        self,
        profile: Profile,
        executor: Executor,
        listener: SessionListener | None = None,
        recover_timeout_s: float = RECOVER_TIMEOUT_S,
        retry_delay_s: float = RETRY_DELAY_S,
    ) -> None:
        self.profile = profile
        self.executor = executor
        self.listener = listener or SessionListener()
        self.recover_timeout_s = recover_timeout_s
        self.retry_delay_s = retry_delay_s
        self.machine = StateMachine(self._on_state)
        self.summary = SessionSummary(profile.name, total=len(profile.actions))
        self.current_index: int | None = None
        self._cancel = threading.Event()  # emergency stop: interrupts waits
        self._stop = threading.Event()  # graceful stop: after the current action
        self._not_paused = threading.Event()
        self._not_paused.set()
        self._confirm = threading.Event()
        self._confirm_answer = False
        self._action_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._started = False
        self._emergency = False
        for a in profile.actions:
            a.status = ActionStatus.PENDING

    # ---------------------------------------------------------------- control
    @property
    def state(self) -> SessionState:
        return self.machine.state

    def pause(self) -> bool:
        if self.machine.try_transition(SessionState.PAUSED):
            self._not_paused.clear()
            self._log("INFO", "Paused (takes effect after the current action).")
            return True
        return False

    def resume(self) -> bool:
        if self.machine.state is SessionState.PAUSED and self.machine.try_transition(SessionState.RUNNING):
            self._not_paused.set()
            self._log("INFO", "Resumed.")
            return True
        return False

    def stop(self) -> bool:
        if self._stop.is_set():
            return False
        self._stop.set()
        moved = self.machine.try_transition(SessionState.STOPPING)
        self._not_paused.set()
        self._log("INFO", "Stop requested: finishing the current action.")
        return moved

    def emergency_stop(self) -> None:
        self._emergency = True
        self._cancel.set()
        self._stop.set()
        self._confirm_answer = False
        self._confirm.set()
        self._not_paused.set()
        self.machine.try_transition(SessionState.STOPPING)
        self._log("WARNING", "EMERGENCY STOP: interrupting the current action.")

    def respond_confirmation(self, answer: bool) -> None:
        self._confirm_answer = answer
        self._confirm.set()

    # -------------------------------------------------------------------- run
    def run(self) -> SessionSummary:
        with self._run_lock:
            if self._started:
                raise RuntimeError("A session can only be run once.")
            self._started = True
        failed = False
        try:
            self.machine.transition(SessionState.PREPARING)
            self._log("INFO", f"Preparing session '{self.profile.name}' ({len(self.profile.actions)} actions).")
            try:
                problems = self.executor.preflight(self.profile)
            except (AdbError, Exception) as exc:  # noqa: BLE001
                problems = [f"Pre-session check failed: {exc}"]
            if problems:
                for p in problems:
                    self._log("ERROR", p)
                raise _Abort(problems[0] + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
            if not self._stop.is_set():
                self.machine.transition(SessionState.RUNNING)
                self._log("INFO", "Session running.")
                failed = self._loop()
        except _Abort as exc:
            failed = True
            self.summary.last_error = str(exc)
            self._log("ERROR", f"Session failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - never leave the session hanging
            failed = True
            self.summary.last_error = f"Internal error: {exc}"
            logger.exception("Automation session crashed")
        finally:
            self._finish(failed)
        return self.summary

    def _loop(self) -> bool:
        for index, action in enumerate(self.profile.actions):
            if self._stop.is_set():
                break
            self._not_paused.wait()
            if self._stop.is_set():
                break
            self.current_index = index
            if action.type is ActionType.END_SESSION:
                action.status = ActionStatus.SUCCEEDED
                self._notify(index, action)
                self._log("INFO", "END_SESSION reached.")
                for rest in self.profile.actions[index + 1 :]:
                    rest.status = ActionStatus.SKIPPED
                return False
            outcome = self._run_action(index, action)
            if outcome.status is ActionStatus.CANCELLED:
                break
            if outcome.status is ActionStatus.FAILED:
                if action.error_policy is ErrorPolicy.SKIP:
                    self._log("WARNING", f"Action {index + 1} failed; continuing (policy SKIP).")
                    continue
                self.summary.last_error = f"Action {index + 1} ({action.type.value}) failed: {outcome.message}"
                return True
        return False

    def _run_action(self, index: int, action: Action) -> ActionOutcome:
        attempts = 1 + (action.max_retries if action.error_policy is ErrorPolicy.RETRY else 0)
        outcome = ActionOutcome(ActionStatus.FAILED, "not executed")
        for attempt in range(1, attempts + 1):
            action.status = ActionStatus.RUNNING
            self._notify(index, action)
            suffix = f" (attempt {attempt}/{attempts})" if attempts > 1 else ""
            self._log("INFO", f"Action {index + 1}: {action.type.value} {action.summary()}{suffix}")
            outcome = self._execute_once(action)
            if outcome.status is not ActionStatus.FAILED or attempt == attempts:
                break
            self._log("WARNING", f"Action {index + 1} failed: {outcome.message}; retrying.")
            if self._cancel.wait(self.retry_delay_s) or self._stop.is_set():
                outcome = ActionOutcome(ActionStatus.CANCELLED, "Stopped before retry.")
                break
        action.status = outcome.status
        self._notify(index, action)
        level = {"FAILED": "ERROR", "UNKNOWN": "WARNING", "CANCELLED": "WARNING"}.get(outcome.status.value, "INFO")
        self._log(level, f"Action {index + 1} {outcome.status.value}: {outcome.message}")
        return outcome

    def _execute_once(self, action: Action, recovered: bool = False) -> ActionOutcome:
        if not self._action_lock.acquire(blocking=False):
            return ActionOutcome(ActionStatus.FAILED, "Another action is still executing (duplicate blocked).")
        try:
            started = time.monotonic()
            if action.type is ActionType.USER_CONFIRMATION:
                outcome = self._ask_user(str(action.params.get("message", "Continue?")), action.timeout_s)
            else:
                outcome = self.executor.execute(action, self._cancel)
            elapsed = time.monotonic() - started
            if outcome.status is not ActionStatus.CANCELLED and elapsed > action.timeout_s * 1.5 + 2:
                outcome = ActionOutcome(ActionStatus.FAILED, f"Timed out ({elapsed:.1f}s > {action.timeout_s:.0f}s).")
            if action.expected_state and outcome.status in (ActionStatus.SUCCEEDED, ActionStatus.UNKNOWN):
                verified = self.executor.verify_expected(action.expected_state, action.timeout_s, self._cancel)
                outcome = ActionOutcome(verified.status, f"{outcome.message} | {verified.message}".strip(" |"))
            return outcome
        except Cancelled:
            return ActionOutcome(ActionStatus.CANCELLED, "Interrupted by emergency stop.")
        except (AdbNotFoundError, AdbNotConfiguredError) as exc:
            raise _Abort(str(exc)) from exc
        except AdbError as exc:
            if recovered or self.executor.check_connection():
                return ActionOutcome(ActionStatus.FAILED, str(exc))
            self._log("WARNING", f"Device connection lost ({exc}); trying to recover for {self.recover_timeout_s:.0f}s.")
            self._action_lock.release()
            try:
                if not self.executor.recover(self.recover_timeout_s, self._cancel):
                    if self._cancel.is_set():
                        return ActionOutcome(ActionStatus.CANCELLED, "Stopped during recovery.")
                    raise _Abort(f"Device disconnected and did not come back: {exc}")
                self._log("INFO", "Device reconnected; repeating the action once.")
                return self._execute_once(action, recovered=True)
            finally:
                self._action_lock.acquire()
        except Exception as exc:  # noqa: BLE001 - reported as an action failure, not swallowed
            logger.debug("Action raised", exc_info=True)
            return ActionOutcome(ActionStatus.FAILED, str(exc) or type(exc).__name__)
        finally:
            self._action_lock.release()

    def _ask_user(self, message: str, timeout_s: float) -> ActionOutcome:
        self._confirm.clear()
        self._confirm_answer = False
        self.listener.on_confirmation(message)
        if not self._confirm.wait(timeout_s):
            return ActionOutcome(ActionStatus.FAILED, "No answer before the timeout.")
        if self._cancel.is_set():
            raise Cancelled()
        if self._confirm_answer:
            return ActionOutcome(ActionStatus.SUCCEEDED, "Confirmed by user.")
        return ActionOutcome(ActionStatus.FAILED, "Declined by user.")

    def _finish(self, failed: bool) -> None:
        for a in self.profile.actions:
            if a.status in (ActionStatus.PENDING, ActionStatus.RUNNING):
                a.status = ActionStatus.CANCELLED
        s = self.summary
        counts = {st: sum(1 for a in self.profile.actions if a.status is st) for st in ActionStatus}
        s.succeeded, s.failed = counts[ActionStatus.SUCCEEDED], counts[ActionStatus.FAILED]
        s.unknown, s.skipped = counts[ActionStatus.UNKNOWN], counts[ActionStatus.SKIPPED]
        s.cancelled = counts[ActionStatus.CANCELLED]
        s.ended_at = datetime.now()
        state = self.machine.state
        if failed:
            if state is SessionState.IDLE:
                self.machine.transition(SessionState.PREPARING)
            self.machine.try_transition(SessionState.FAILED)
            s.result = "FAILED"
        elif self._stop.is_set():
            self.machine.try_transition(SessionState.STOPPING)
            self.machine.try_transition(SessionState.IDLE)
            s.result = "EMERGENCY_STOPPED" if self._emergency else "STOPPED"
        else:
            if state is SessionState.PAUSED:
                self.machine.try_transition(SessionState.RUNNING)
            self.machine.try_transition(SessionState.COMPLETED)
            s.result = "COMPLETED"
        self._log(
            "INFO" if s.result == "COMPLETED" else "WARNING",
            f"Session {s.result}: {s.succeeded} succeeded, {s.unknown} unverified, {s.failed} failed, "
            f"{s.cancelled} cancelled.",
        )

    # ---------------------------------------------------------------- helpers
    def _on_state(self, old: SessionState, new: SessionState) -> None:
        self.listener.on_state(old, new)

    def _notify(self, index: int, action: Action) -> None:
        self.listener.on_action(index, action)

    def _log(self, level: str, message: str) -> None:
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.profile.name, message)
        self.listener.on_log(level, message)
