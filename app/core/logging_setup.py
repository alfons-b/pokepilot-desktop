"""Application-wide logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_FILE_HANDLER_NAME = "pokepilot-file"
_CONSOLE_HANDLER_NAME = "pokepilot-console"


def setup_logging(logs_dir: Path, level: str = "INFO") -> Path:
    """Configure root logging to a rotating file and stderr. Idempotent."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "pokepilot.log"
    root = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)

    names = {h.get_name() for h in root.handlers}
    if _FILE_HANDLER_NAME not in names:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        fh.set_name(_FILE_HANDLER_NAME)
        fh.setFormatter(formatter)
        root.addHandler(fh)
    if _CONSOLE_HANDLER_NAME not in names:
        ch = logging.StreamHandler()
        ch.set_name(_CONSOLE_HANDLER_NAME)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    set_log_level(level)
    return log_file


def set_log_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
