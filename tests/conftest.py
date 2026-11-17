from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from app.core.config import AppConfig, ConfigManager  # noqa: E402

FAKES_DIR = Path(__file__).parent / "fakes"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own POKEPILOT_HOME so real user data is never touched."""
    home = tmp_path / "home"
    monkeypatch.setenv("POKEPILOT_HOME", str(home))
    return home


@pytest.fixture
def config_manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(tmp_path / "cfg" / "config.json")


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(adb_path="/fake/adb", auto_refresh_enabled=False)


@pytest.fixture
def fake_adb_exe(tmp_path: Path) -> Path:
    """An executable 'adb' wrapper that runs tests/fakes/fake_adb.py with this interpreter."""
    script = FAKES_DIR / "fake_adb.py"
    if sys.platform == "win32":
        exe = tmp_path / "adb.bat"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "adb"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe
