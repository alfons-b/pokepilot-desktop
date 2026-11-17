from __future__ import annotations

import threading

import pytest

from app.automation.models import Action, ActionType, Profile
from app.automation.repository import ProfileRepository
from app.automation.session_manager import SessionManager
from app.automation.state_machine import SessionState
from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.database.db import Database
from app.emulator.adb_client import AdbClient
from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository
from app.pgsharp.controller import PgsharpController
from app.pgsharp.layout import LayoutStore
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_ONE, standard_runner


@pytest.fixture
def env(qtbot, config_manager, config, tmp_path):
    created = []

    def factory(devices=DEVICES_ONE):
        fake = standard_runner(devices)
        runner = TaskRunner()
        ctrl = DeviceController(config_manager, config, runner,
                                client_factory=lambda p, t: AdbClient(p, runner=fake, timeout=t))
        with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=3000):
            ctrl.refresh_devices()
        db = Database(tmp_path / "t.db")
        ex = FakeExecutor()
        mgr = SessionManager(
            ctrl, AppController(ctrl, runner), PgsharpController(ctrl, runner, LayoutStore(tmp_path / "l.json")),
            ProfileRepository(db), SessionHistoryRepository(db), ActivityLogRepository(db),
            executor_factory=lambda *a: ex,
        )
        created.append(mgr)
        return mgr, ctrl, ex, db

    yield factory
    for m in created:
        m.shutdown()


def finished(qtbot, mgr, fn):
    with qtbot.waitSignal(mgr.session_finished, timeout=5000) as sig:
        assert fn()
    mgr.wait(3)
    return sig.args[0]


def test_session_runs_and_records_history(qtbot, env):
    mgr, _, ex, db = env()
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.PRESS_BACK), Action(ActionType.PRESS_BACK)]))
    summary = finished(qtbot, mgr, lambda: mgr.start(pid))
    assert summary.result == "COMPLETED"
    rec = SessionHistoryRepository(db).recent()[0]
    assert rec.result == "COMPLETED" and rec.succeeded == 2 and rec.profile_name == "p"
    logs = ActivityLogRepository(db).recent(50, session_id=rec.id)
    assert any("COMPLETED" in r["message"] for r in logs)
    assert mgr.current_profile_id == pid


def test_start_requirements(qtbot, env):
    mgr, ctrl, _, _ = env(DEVICES_MULTI)  # no device selected
    with qtbot.waitSignal(mgr.operation_failed, timeout=1000):
        assert mgr.start(None) is False
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.PRESS_BACK)]))
    with qtbot.waitSignal(mgr.operation_failed, timeout=1000) as sig:
        assert mgr.start(pid) is False
    assert "online device" in sig.args[1]
    ctrl.select_device("emulator-5554")
    with qtbot.waitSignal(mgr.operation_failed, timeout=1000):
        assert mgr.start(99999) is False


def test_only_one_session_at_a_time(qtbot, env):
    mgr, _, ex, _ = env()
    gate = threading.Event()
    ex.on_execute = lambda a: gate.wait(3)
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.PRESS_BACK)]))
    assert mgr.start(pid)
    with qtbot.waitSignal(mgr.operation_failed, timeout=1000) as sig:
        assert mgr.start(pid) is False
    assert "already running" in sig.args[1]
    gate.set()
    mgr.wait(3)


def test_controls_and_state_signals(qtbot, env):
    mgr, _, ex, _ = env()
    gate = threading.Event()
    ex.on_execute = lambda a: gate.wait(3)  # hold each action until released
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.PRESS_BACK), Action(ActionType.PRESS_BACK)]))
    states = []
    mgr.state_changed.connect(states.append)
    assert mgr.start(pid)
    qtbot.waitUntil(lambda: mgr.state is SessionState.RUNNING, timeout=3000)
    assert mgr.pause()
    assert mgr.resume()
    with qtbot.waitSignal(mgr.session_finished, timeout=5000) as sig:
        mgr.emergency_stop()
        gate.set()
    assert sig.args[0].result == "EMERGENCY_STOPPED"
    qtbot.waitUntil(lambda: SessionState.IDLE in states, timeout=2000)


def test_confirmation_round_trip(qtbot, env):
    mgr, _, _, _ = env()
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.USER_CONFIRMATION, {"message": "OK?"}, 5)]))
    mgr.confirmation_requested.connect(lambda msg: mgr.respond_confirmation(True))
    assert finished(qtbot, mgr, lambda: mgr.start(pid)).result == "COMPLETED"


def test_device_change_stops_session(qtbot, env):
    mgr, ctrl, ex, _ = env(DEVICES_MULTI)
    ctrl.select_device("emulator-5554")
    gate = threading.Event()
    ex.on_execute = lambda a: gate.wait(3)
    pid = mgr.profiles.save(Profile("p", actions=[Action(ActionType.PRESS_BACK), Action(ActionType.PRESS_BACK)]))
    assert mgr.start(pid)
    qtbot.waitUntil(lambda: mgr.state is SessionState.RUNNING, timeout=3000)
    with qtbot.waitSignal(mgr.session_finished, timeout=5000) as sig:
        ctrl.select_device("127.0.0.1:5555")
        gate.set()
    assert sig.args[0].result == "STOPPED"
