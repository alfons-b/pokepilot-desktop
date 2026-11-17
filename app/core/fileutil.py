"""Small filesystem helpers shared by JSON stores."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write text via a temp file + os.replace so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def backup_corrupt(path: Path) -> Path | None:
    """Rename a corrupt file aside as <name>.corrupt-<timestamp>. Returns the new path or None."""
    backup = path.with_name(f"{path.name}.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
    try:
        os.replace(path, backup)
        return backup
    except OSError:
        return None
