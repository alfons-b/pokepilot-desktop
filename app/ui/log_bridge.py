"""Forward Python log records to the GUI thread safely."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    level: str
    levelno: int
    logger: str
    message: str

    def format(self) -> str:
        return f"{self.timestamp:%H:%M:%S}  {self.level:<7} {self.message}"


class _Emitter(QObject):
    record = Signal(object)  # LogEntry


class QtLogHandler(logging.Handler):
    """Logging handler that emits a Qt signal per record and keeps a ring buffer.

    The signal may be emitted from worker threads; receivers that are QObject
    methods in the GUI thread get it via a queued connection.
    """

    def __init__(self, capacity: int = 1000, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.emitter = _Emitter()
        self._buffer: deque[LogEntry] = deque(maxlen=capacity)

    @property
    def entries(self) -> list[LogEntry]:
        return list(self._buffer)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info and record.levelno >= logging.ERROR:
                msg += f" ({record.exc_info[1]})"
            entry = LogEntry(
                datetime.fromtimestamp(record.created), record.levelname, record.levelno, record.name, msg
            )
            self._buffer.append(entry)
            self.emitter.record.emit(entry)
        except Exception:  # noqa: BLE001
            self.handleError(record)
