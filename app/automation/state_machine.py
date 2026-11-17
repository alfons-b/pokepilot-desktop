"""Explicit, thread-safe session state machine."""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.IDLE: frozenset({SessionState.PREPARING}),
    SessionState.PREPARING: frozenset({SessionState.RUNNING, SessionState.STOPPING, SessionState.FAILED}),
    SessionState.RUNNING: frozenset(
        {SessionState.PAUSED, SessionState.STOPPING, SessionState.COMPLETED, SessionState.FAILED}
    ),
    SessionState.PAUSED: frozenset({SessionState.RUNNING, SessionState.STOPPING, SessionState.FAILED}),
    # A user stop ends in IDLE (the session result records "STOPPED"); errors while stopping end in FAILED.
    SessionState.STOPPING: frozenset({SessionState.IDLE, SessionState.FAILED}),
    SessionState.COMPLETED: frozenset({SessionState.IDLE}),
    SessionState.FAILED: frozenset({SessionState.IDLE}),
}

TERMINAL = frozenset({SessionState.COMPLETED, SessionState.FAILED})
ACTIVE = frozenset({SessionState.PREPARING, SessionState.RUNNING, SessionState.PAUSED, SessionState.STOPPING})


class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, on_change: Callable[[SessionState, SessionState], None] | None = None) -> None:
        self._state = SessionState.IDLE
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> SessionState:
        return self._state

    def can(self, target: SessionState) -> bool:
        return target in TRANSITIONS[self._state]

    def transition(self, target: SessionState) -> SessionState:
        with self._lock:
            old = self._state
            if target not in TRANSITIONS[old]:
                raise InvalidTransition(f"{old.value} -> {target.value} is not allowed")
            self._state = target
        if self._on_change:
            self._on_change(old, target)
        return old

    def try_transition(self, target: SessionState) -> bool:
        try:
            self.transition(target)
        except InvalidTransition:
            return False
        return True
