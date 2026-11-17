from __future__ import annotations

import pytest

from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.emulator.adb_client import AdbClient
from app.pgsharp import controller as pgc
from app.pgsharp.controller import PgsharpController
from app.pgsharp.layout import Availability, FeatureMapping, LayoutStore
from app.pgsharp.ui_driver import Outcome
from tests.fakes.fake_device import HOME, MENU, screen_png
from tests.fakes.fake_runner import DEVICES_ONE, standard_runner


class Bin:
    def __init__(self, png: bytes) -> None:
        self.png = png

    def __call__(self, args, timeout):
        return 0, self.png, ""


@pytest.fixture
def make(qtbot, config_manager, config, tmp_path):
    def factory(png=HOME):
        fake = standard_runner(DEVICES_ONE)
        fake.set(["shell", "input", "tap", "270", "600"], "")
        screen = Bin(png)
        runner = TaskRunner()
        ctrl = DeviceController(
            config_manager, config, runner,
            client_factory=lambda p, t: AdbClient(p, runner=fake, timeout=t, binary_runner=screen),
        )
        with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=3000):
            ctrl.refresh_devices()
        pg = PgsharpController(ctrl, runner, LayoutStore(tmp_path / "layout.json"))
        return pg, screen, fake

    return factory


def capture(qtbot, pg):
    with qtbot.waitSignal(pg.screenshot_ready, timeout=3000):
        assert pg.capture()


def test_capture_and_add_element_sets_reference(qtbot, make, tmp_path):
    pg, _, _ = make()
    capture(qtbot, pg)
    assert pg.image.width() == 540
    el = pg.add_element("Menu button", 0.5, 0.5)
    assert el.id == "menu_button"
    assert (pg.layout.reference_width, pg.layout.reference_height) == (540, 1200)
    reloaded, _ = LayoutStore(tmp_path / "layout.json").load()
    assert "menu_button" in reloaded.elements


def test_resolution_mismatch_blocks_calibration(qtbot, make):
    pg, screen, _ = make()
    capture(qtbot, pg)
    pg.add_element("menu", 0.5, 0.5)
    screen.png = screen_png(1200, 540)  # rotated
    with qtbot.waitSignal(pg.layout_warning, timeout=3000):
        pg.capture()
    with qtbot.waitSignal(pg.operation_failed, timeout=1000):
        assert pg.add_element("other", 0.1, 0.1) is None


def test_region_requires_screenshot_and_state(qtbot, make):
    pg, _, _ = make()
    with qtbot.waitSignal(pg.operation_failed, timeout=1000):
        assert pg.add_region("x", 0, 0, 0.1, 0.1) is False
    capture(qtbot, pg)
    with qtbot.waitSignal(pg.operation_failed, timeout=1000):
        assert pg.add_region("missing", 0, 0, 0.1, 0.1) is False


def test_verify_now_and_layout_change_warning(qtbot, make, monkeypatch):
    pg, screen, _ = make(MENU)
    capture(qtbot, pg)
    st = pg.add_state("Menu open")
    assert pg.add_region(st.id, 0, 0, 0.5, 0.1)
    with qtbot.waitSignal(pg.verification_done, timeout=3000) as sig:
        pg.verify_now()
    assert sig.args[0][0].matched is True
    assert pg.last_verified[1] == "Menu open"
    screen.png = HOME
    for _ in range(pgc.LAYOUT_FAILURE_LIMIT - 1):
        with qtbot.waitSignal(pg.verification_done, timeout=3000):
            pg.verify_now()
    with qtbot.waitSignal(pg.layout_warning, timeout=3000) as warn:
        pg.verify_now()
    assert "may have changed" in warn.args[0]


def test_verify_without_states_fails(qtbot, make):
    pg, _, _ = make()
    with qtbot.waitSignal(pg.operation_failed, timeout=1000):
        assert pg.verify_now() is False


def test_feature_test(qtbot, make):
    pg, _, fake = make(MENU)
    capture(qtbot, pg)
    pg.add_element("menu", 0.5, 0.5)
    st = pg.add_state("menu open")
    pg.add_region(st.id, 0, 0, 0.5, 0.1)
    assert pg.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], None, st.id))
    with qtbot.waitSignal(pg.feature_tested, timeout=5000) as sig:
        pg.test_feature("teleport")
    assert sig.args[0].outcome is Outcome.SUCCESS
    assert ("-s", "emulator-5554", "shell", "input", "tap", "270", "600") in fake.calls


def test_invalid_feature_mapping_rejected(qtbot, make):
    pg, _, _ = make()
    with qtbot.waitSignal(pg.operation_failed, timeout=1000):
        assert pg.update_feature(FeatureMapping("teleport", open_steps=["nope"])) is False
