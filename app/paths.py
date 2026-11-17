"""Filesystem locations used by the application.

Resolution order for the application home directory:

1. ``POKEPILOT_HOME`` environment variable (used by tests and portable setups).
2. When frozen by PyInstaller: ``%LOCALAPPDATA%\\PokePilot`` (Program Files is not writable).
3. In development: the project root (so ``data/`` and ``logs/`` sit next to the source).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def app_home() -> Path:
    override = os.environ.get("POKEPILOT_HOME")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "PokePilot"
    return PROJECT_ROOT


def data_dir() -> Path:
    path = app_home() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def assets_dir() -> Path:
    # PyInstaller unpacks bundled data into sys._MEIPASS.
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return base / "assets"
