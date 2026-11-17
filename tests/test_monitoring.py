from __future__ import annotations

import logging

import pytest

from app.automation.repository import ProfileRepository
from app.automation.session_manager import SessionManager
from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.database.db import Database
from app.emulator.adb_client import AdbClient
from app.emulator.instances import EmulatorInstance
from app.emulator.models import AdbDevice, DeviceInfo, DeviceState
from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository
from app.monitoring.monitor import POKEMON_GO_PACKAGE, StatusMonitor
from app.monitoring.repositories import (
    DatabaseLogHandler,
    DeviceRepository,
    EmulatorConfigRepository,
    SettingsRepository,
)
from app.pgsharp.controller import PgsharpController
from app.pgsharp.layout import LayoutStore
from app.screen.mirror_controller import MirrorController
from tests.fakes.fake_runner import DEVICES_ONE, TARGET_PKG, standard_runner


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "m.db")
    yield d
    d.close()


def test_device_repository(db):
    repo = DeviceRepository(db)
    repo.upsert_seen([AdbDevice("emulator-5554", DeviceState.DEVICE, "device", model="Pixel")])
    repo.upsert_seen([AdbDevice("emulator-5554", DeviceState.OFFLINE, "offline")])  # model kept
    repo.update_info(DeviceInfo("emulator-5554", "13", "33", model="Pixel 7", physical_resolution=(1080, 2400)))
    [row] = repo.all()
    assert row["last_state"] == "offline" and row["model"] == "Pixel 7"
    assert row["android_version"] == "13" and row["resolution"] == "1080 x 2400"


def test_emulator_config_repository(db):
    repo = EmulatorConfigRepository(db)
    inst = EmulatorInstance("BlueStacks", "Pie64", "Main", "127.0.0.1:5555", "C:/HD-Player.exe", ("--instance", "Pie64"))
    repo.upsert([inst])
    repo.upsert([EmulatorInstance("BlueStacks", "Pie64", "Renamed", "127.0.0.1:5565")])
    [row] = repo.all()
    assert row["display_name"] == "Renamed" and row["adb_address"] == "127.0.0.1:5565"


def test_settings_repository(db):
    repo = SettingsRepository(db)
    assert repo.get("x", "d") == "d"
    repo.set("x", "1")
    repo.set("x", "2")
    assert repo.get("x") == "2"


def test_database_log_handler(db):
    logs = ActivityLogRepository(db)
    handler = DatabaseLogHandler(logs)
    handler.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("app.test_component")
    lg.addHandler(handler)
    lg.propagate = False
    try:
        lg.info("ignored info")
        lg.warning("disk almost full")
        logging.getLogger("app.database.x").addHandler(handler)
        logging.getLogger("app.database.x").error("not recorded (recursion guard)")
    finally:
        lg.removeHandler(handler)
        logging.getLogger("app.database.x").removeHandler(handler)
        lg.propagate = True
    rows = logs.recent(10)
    assert [r["message"] for r in rows] == ["disk almost full"]
    assert rows[0]["source"] == "app.test_component"


@pytest.fixture
def monitor_env(qtbot, config_manager, config, tmp_path):
    def factory(fake=None):
        fake = fake or standard_runner(DEVICES_ONE)
        runner = TaskRunner()
        ctrl = DeviceController(config_manager, config, runner,
                                client_factory=lambda p, t: AdbClient(p, runner=fake, timeout=t))
        apps = AppController(ctrl, runner)
        pg = PgsharpController(ctrl, runner, LayoutStore(tmp_path / "l.json"))
        d = Database(tmp_path / "s.db")
        sessions = SessionManager(ctrl, apps, pg, ProfileRepository(d), SessionHistoryRepository(d))
        mon = StatusMonitor(ctrl, apps, MirrorController(ctrl, runner), pg, sessions, runner)
        return mon, ctrl, apps, fake

    return factory


def test_monitor_snapshot_reflects_state(qtbot, monitor_env):
    mon, ctrl, apps, fake = monitor_env()
    assert mon.snapshot.emulator == "No device selected"
    with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=3000):
        ctrl.refresh_devices()
    assert mon.snapshot.emulator.endswith("(emulator-5554): device")
    assert mon.snapshot.adb.startswith("Connected")
    assert mon.snapshot.scrcpy == "Not running"
    assert mon.snapshot.session_state == "IDLE"


def test_monitor_polls_apps(qtbot, monitor_env):
    fake = standard_runner(DEVICES_ONE)
    fake.set(["shell", "pm", "path", POKEMON_GO_PACKAGE], "", returncode=1)
    mon, ctrl, apps, _ = monitor_env(fake)
    assert mon.poll_apps() is False  # no device yet
    with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=3000):
        ctrl.refresh_devices()
    apps.set_target_package(TARGET_PKG)
    with qtbot.waitSignal(mon.changed, check_params_cb=lambda s: s.pokemon_go != "Not checked", timeout=3000):
        assert mon.poll_apps()
    assert mon.snapshot.pgsharp.startswith("Running")
    assert mon.snapshot.pokemon_go.startswith("Not installed")
    fake.set(["shell", "pm", "path", POKEMON_GO_PACKAGE], "package:/data/app/base.apk")
    fake.set(["shell", "pidof", POKEMON_GO_PACKAGE], "", returncode=1)
    qtbot.waitUntil(lambda: not mon._polling, timeout=2000)
    with qtbot.waitSignal(mon.changed, check_params_cb=lambda s: s.pokemon_go == "Not running", timeout=3000):
        mon.poll_apps()


def test_monitor_records_errors(monitor_env):
    mon, *_ = monitor_env()
    mon.note_error("something broke")
    assert "something broke" in mon.snapshot.last_error
