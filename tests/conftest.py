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


def make_wrapper(directory: Path, name: str, script: Path) -> Path:
    """Create an executable that runs ``script`` with this interpreter."""
    if sys.platform == "win32":
        exe = directory / f"{name}.bat"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        exe = directory / name
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


@pytest.fixture
def fake_adb_exe(tmp_path: Path) -> Path:
    """An executable 'adb' wrapper that runs tests/fakes/fake_adb.py with this interpreter."""
    return make_wrapper(tmp_path, "adb", FAKES_DIR / "fake_adb.py")


@pytest.fixture
def fake_scrcpy_exe(tmp_path: Path) -> Path:
    return make_wrapper(tmp_path, "scrcpy", FAKES_DIR / "fake_scrcpy.py")


def png_bytes(width: int = 8, height: int = 16) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)
