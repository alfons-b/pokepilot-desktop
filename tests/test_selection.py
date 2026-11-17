from app.emulator.models import AdbDevice, DeviceState
from app.emulator.selection import choose_selected_serial

A = AdbDevice("emulator-5554", DeviceState.DEVICE)
B = AdbDevice("127.0.0.1:5555", DeviceState.DEVICE)
C_OFF = AdbDevice("127.0.0.1:5565", DeviceState.OFFLINE)


def test_no_devices():
    assert choose_selected_serial([], None, None) is None
    assert choose_selected_serial([], "emulator-5554", "emulator-5554") is None


def test_single_online_device_auto_selected():
    assert choose_selected_serial([A], None, None) == A.serial
    assert choose_selected_serial([A, C_OFF], None, None) == A.serial


def test_multiple_devices_require_explicit_choice():
    assert choose_selected_serial([A, B], None, None) is None


def test_current_selection_kept():
    assert choose_selected_serial([A, B], B.serial, A.serial) == B.serial


def test_current_kept_even_if_offline():
    assert choose_selected_serial([A, C_OFF], C_OFF.serial, None) == C_OFF.serial


def test_preferred_restored():
    assert choose_selected_serial([A, B], None, B.serial) == B.serial


def test_missing_current_falls_back():
    assert choose_selected_serial([A, B], "gone", None) is None
    assert choose_selected_serial([A], "gone", None) == A.serial


def test_only_offline_device_not_auto_selected():
    assert choose_selected_serial([C_OFF], None, None) is None
