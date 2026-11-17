"""Run blocking work (ADB, subprocesses) off the GUI thread.

Callbacks are always invoked on the thread that owns the :class:`TaskRunner`
(the GUI thread), because worker signals are routed through bound slots of
the runner itself, which Qt delivers as queued connections.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    result = Signal(int, object)
    error = Signal(int, object)
    finished = Signal(int)


class _Worker(QRunnable):
    def __init__(self, task_id: int, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.task_id = task_id
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            value = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, never swallowed
            logger.debug("Task %s raised %r", self.task_id, exc)
            self.signals.error.emit(self.task_id, exc)
        else:
            self.signals.result.emit(self.task_id, value)
        finally:
            self.signals.finished.emit(self.task_id)


@dataclass
class _Callbacks:
    on_result: Callable[[Any], None] | None
    on_error: Callable[[Exception], None] | None
    on_finished: Callable[[], None] | None
    signals: _WorkerSignals  # keep alive until finished
    name: str


class TaskRunner(QObject):
    """Thread-pool front end with main-thread callbacks."""

    active_count_changed = Signal(int)

    def __init__(self, max_threads: int = 4, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._ids = itertools.count(1)
        self._tasks: dict[int, _Callbacks] = {}

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> int:
        task_id = next(self._ids)
        worker = _Worker(task_id, fn, args, kwargs)
        worker.signals.result.connect(self._handle_result)
        worker.signals.error.connect(self._handle_error)
        worker.signals.finished.connect(self._handle_finished)
        self._tasks[task_id] = _Callbacks(
            on_result, on_error, on_finished, worker.signals, name or getattr(fn, "__name__", "task")
        )
        self._pool.start(worker)
        self.active_count_changed.emit(self.active_count)
        return task_id

    def wait_for_done(self, msecs: int = 5000) -> bool:
        return self._pool.waitForDone(msecs)

    @Slot(int, object)
    def _handle_result(self, task_id: int, value: object) -> None:
        cb = self._tasks.get(task_id)
        if cb and cb.on_result:
            self._safe_call(cb.on_result, value, task=cb.name)

    @Slot(int, object)
    def _handle_error(self, task_id: int, exc: object) -> None:
        cb = self._tasks.get(task_id)
        if cb is None:
            return
        if cb.on_error:
            self._safe_call(cb.on_error, exc, task=cb.name)
        else:
            logger.error("Background task '%s' failed: %s", cb.name, exc)

    @Slot(int)
    def _handle_finished(self, task_id: int) -> None:
        cb = self._tasks.pop(task_id, None)
        if cb and cb.on_finished:
            self._safe_call(cb.on_finished, task=cb.name)
        self.active_count_changed.emit(self.active_count)

    @staticmethod
    def _safe_call(fn: Callable[..., None], *args: Any, task: str) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            logger.exception("Callback for task '%s' raised", task)
