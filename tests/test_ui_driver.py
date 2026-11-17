import threading

import pytest
from PySide6.QtGui import QImage

from app.pgsharp import vision
from app.pgsharp.layout import Availability, FeatureMapping, PgsharpLayout
from app.pgsharp.ui_driver import Cancelled, DriverError, Outcome, UiDriver
from tests.fakes.fake_device import HOME, MENU, FakeDevice


def layout_with_menu() -> PgsharpLayout:
    lay = PgsharpLayout()
    lay.set_reference(540, 1200)
    lay.add_element("menu", 0.5, 0.5)
    st = lay.add_state("menu_open")
    st.regions.append(vision.make_region(QImage.fromData(MENU, "PNG"), 0, 0, 0.5, 0.1))
    lay.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], None, "menu_open"))
    return lay


def drv(dev, lay=None):
    return UiDriver(dev, "emulator-5554", lay or layout_with_menu(), sleep=lambda _s: None, step_delay_s=0)


def test_requires_serial():
    with pytest.raises(DriverError):
        UiDriver(FakeDevice(), "", PgsharpLayout())


def test_tap_element_uses_current_resolution():
    dev = FakeDevice([HOME])
    d = drv(dev)
    d.tap_element("menu")
    assert dev.taps == [(270, 600)]  # 0.5 * (540-1), 0.5 * (1200-1)
    with pytest.raises(DriverError):
        d.tap_element("unknown")
    with pytest.raises(DriverError):
        d.tap_norm(1.2, 0)


def test_swipe_and_back_validation():
    dev = FakeDevice([HOME])
    d = drv(dev)
    d.swipe_norm(0.1, 0.9, 0.1, 0.1, 400)
    assert dev.swipes[0][-1] == 400
    with pytest.raises(DriverError):
        d.swipe_norm(0, 0, 2, 0)
    with pytest.raises(DriverError):
        d.swipe_norm(0, 0, 1, 1, 10)
    d.back()
    assert dev.keys == [4]


def test_open_feature_success_requires_verification():
    dev = FakeDevice([HOME])
    dev.after_tap = MENU
    result = drv(dev).open_feature("teleport")
    assert result.outcome is Outcome.SUCCESS
    assert dev.taps


def test_open_feature_tap_without_effect_fails():
    dev = FakeDevice([HOME])  # screen never changes
    result = drv(dev).open_feature("teleport")
    assert result.outcome is Outcome.FAILED
    assert "not detected" in result.message


def test_open_feature_without_verify_state_is_unknown():
    lay = layout_with_menu()
    lay.update_feature(FeatureMapping("teleport", Availability.AVAILABLE, ["menu"], None, None))
    assert drv(FakeDevice([HOME]), lay).open_feature("teleport").outcome is Outcome.UNKNOWN


def test_unavailable_and_unmapped_features():
    lay = layout_with_menu()
    lay.update_feature(FeatureMapping("teleport", Availability.UNAVAILABLE, ["menu"]))
    dev = FakeDevice([HOME])
    assert drv(dev, lay).open_feature("teleport").outcome is Outcome.FAILED
    assert dev.taps == []  # nothing was tapped
    assert drv(dev, lay).open_feature("joystick").outcome is Outcome.FAILED
    assert drv(dev, lay).toggle_feature("joystick").outcome is Outcome.FAILED


def test_wait_for_state_polls_and_cancels():
    dev = FakeDevice([HOME, HOME, MENU])
    match = drv(dev).wait_for_state("menu_open", timeout_s=5, poll_s=0)
    assert match.matched
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        drv(FakeDevice([HOME])).wait_for_state("menu_open", 5, cancel=cancel)


def test_wait_for_state_timeout_returns_last_mismatch():
    match = drv(FakeDevice([HOME])).wait_for_state("menu_open", timeout_s=0, poll_s=0)
    assert match.matched is False


def test_resolution_warning():
    lay = layout_with_menu()
    from tests.fakes.fake_device import screen_png

    assert drv(FakeDevice([screen_png(1200, 540)]), lay).resolution_warning() is not None
    assert drv(FakeDevice([HOME]), lay).resolution_warning() is None
