import threading

import pytest
from PySide6.QtGui import QImage

from app.automation.engine import AutomationSession
from app.automation.executor import DeviceExecutor
from app.automation.models import Action, ActionStatus, ActionType, Profile
from app.emulator.adb_client import AdbClient
from app.pgsharp import vision
from app.pgsharp.layout import Availability, FeatureMapping, PgsharpLayout
from app.pgsharp.ui_driver import Cancelled
from tests.fakes.fake_device import HOME, MENU, screen_png
from tests.fakes.fake_runner import TARGET_PKG, standard_runner


class Screen:
    def __init__(self, png=HOME):
        self.png = png

    def __call__(self, args, timeout):
        return 0, self.png, ""


def layout():
    lay = PgsharpLayout()
    lay.set_reference(540, 1200)
    lay.add_element("menu", 0.5, 0.5)
    st = lay.add_state("menu open")
    st.regions.append(vision.make_region(QImage.fromData(MENU, "PNG"), 0, 0, 0.5, 0.1))
    lay.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], None, "menu_open"))
    return lay


@pytest.fixture
def setup():
    runner = standard_runner()
    screen = Screen()
    client = AdbClient("/fake/adb", runner=runner, binary_runner=screen)
    ex = DeviceExecutor(client, "emulator-5554", layout(), TARGET_PKG, step_delay_s=0)
    return ex, runner, screen


def run(ex, *actions):
    return AutomationSession(Profile("t", actions=list(actions)), ex, retry_delay_s=0).run()


def test_preflight_checks(setup):
    ex, runner, screen = setup
    assert ex.preflight(Profile("t", actions=[Action(ActionType.PRESS_BACK)])) == []
    runner.set(["get-state"], "offline")
    assert "not online" in ex.preflight(Profile("t", actions=[Action(ActionType.PRESS_BACK)]))[0]
    runner.set(["get-state"], "device")
    screen.png = screen_png(1200, 540)
    tap = Action(ActionType.TAP, {"element": "menu"})
    assert any("Recalibrate" in p for p in DeviceExecutor(ex.client, ex.serial, ex.layout).preflight(
        Profile("t", actions=[tap])))
    no_target = DeviceExecutor(ex.client, ex.serial, ex.layout, "")
    assert any("target app" in p for p in no_target.preflight(Profile("t", actions=[Action(ActionType.LAUNCH_APP)])))


def test_tap_is_unknown_without_expected_state(setup):
    ex, runner, _ = setup
    tap = Action(ActionType.TAP, {"element": "menu"})
    summary = run(ex, tap)
    assert tap.status is ActionStatus.UNKNOWN and summary.result == "COMPLETED"
    assert ("-s", "emulator-5554", "shell", "input", "tap", "270", "600") in runner.calls


def test_tap_verified_by_expected_state(setup):
    ex, _, screen = setup
    screen.png = MENU
    tap = Action(ActionType.TAP, {"x": 0.1, "y": 0.1}, timeout_s=2, expected_state="menu_open")
    run(ex, tap)
    assert tap.status is ActionStatus.SUCCEEDED


def test_expected_state_missing_fails(setup):
    ex, _, _ = setup
    tap = Action(ActionType.TAP, {"x": 0.1, "y": 0.1}, timeout_s=1, expected_state="menu_open")
    assert run(ex, tap).result == "FAILED"


def test_launch_wait_screenshot_swipe_back(setup, tmp_path):
    ex, runner, _ = setup
    acts = [Action.create(ActionType.LAUNCH_APP), Action(ActionType.WAIT, {"seconds": 0.1}, 5),
            Action(ActionType.SCREENSHOT, {"label": "after launch"}),
            Action.create(ActionType.SWIPE), Action(ActionType.PRESS_BACK)]
    summary = run(ex, *acts)
    assert summary.result == "COMPLETED"
    assert [a.status for a in acts] == [ActionStatus.SUCCEEDED, ActionStatus.SUCCEEDED, ActionStatus.SUCCEEDED,
                                        ActionStatus.UNKNOWN, ActionStatus.UNKNOWN]
    assert ("-s", "emulator-5554", "shell", "input", "keyevent", "4") in runner.calls


def test_launch_failure(setup):
    ex, runner, _ = setup
    runner.set(["shell", "pidof", TARGET_PKG], "", returncode=1)
    launch = Action.create(ActionType.LAUNCH_APP)
    launch.timeout_s = 3
    assert run(ex, launch).result == "FAILED"


def test_feature_and_wait_for_state(setup):
    ex, _, screen = setup
    screen.png = MENU
    acts = [Action(ActionType.SELECT_FEATURE, {"feature": "teleport"}),
            Action(ActionType.WAIT_FOR_STATE, {"state": "menu_open", "poll_s": 0.2}, timeout_s=2),
            Action(ActionType.OPEN_SCREEN, {"steps": "menu"})]
    run(ex, *acts)
    assert [a.status for a in acts] == [ActionStatus.SUCCEEDED, ActionStatus.SUCCEEDED, ActionStatus.UNKNOWN]


def test_wait_is_cancellable(setup):
    ex, _, _ = setup
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        ex.execute(Action(ActionType.WAIT, {"seconds": 30}, 60), cancel)


def test_recover_reconnects_tcp(setup):
    ex, runner, _ = setup
    ex.serial = "127.0.0.1:5555"
    runner.set(["connect", "127.0.0.1:5555"], "connected to 127.0.0.1:5555")
    assert ex.recover(1, threading.Event())
    assert ("connect", "127.0.0.1:5555") in runner.calls
    runner.set(["get-state"], "", returncode=1, stderr="device not found")
    assert ex.recover(0.1, threading.Event()) is False
