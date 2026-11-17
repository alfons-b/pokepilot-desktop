from app.emulator.adb_parser import (
    parse_adb_version,
    parse_devices_output,
    parse_getprop_output,
    parse_wm_size,
)
from app.emulator.models import DeviceState
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_NONE, DEVICES_ONE, GETPROP_OUTPUT


def test_no_devices():
    assert parse_devices_output(DEVICES_NONE) == []


def test_empty_output():
    assert parse_devices_output("") == []


def test_one_device_with_details():
    [d] = parse_devices_output(DEVICES_ONE)
    assert d.serial == "emulator-5554"
    assert d.state is DeviceState.DEVICE
    assert d.is_online
    assert d.model == "sdk_gphone64_x86_64"
    assert d.product == "sdk_gphone64_x86_64"
    assert d.device == "emu64xa"
    assert d.transport_id == "1"
    assert d.is_emulator_hint
    assert d.connection_type == "Emulator console"


def test_multiple_devices_and_states():
    devices = parse_devices_output(DEVICES_MULTI)
    assert [d.serial for d in devices] == ["emulator-5554", "127.0.0.1:5555", "127.0.0.1:5565"]
    assert devices[1].is_network and devices[1].is_emulator_hint
    assert devices[1].connection_type == "TCP/IP"
    assert devices[2].state is DeviceState.OFFLINE
    assert not devices[2].is_online
    assert devices[2].transport_id == "3"


def test_daemon_messages_are_ignored():
    text = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "emulator-5556\tdevice\n"
    )
    [d] = parse_devices_output(text)
    assert d.serial == "emulator-5556"
    assert d.model == ""


def test_unauthorized_and_unknown_state():
    text = "List of devices attached\nABC123 unauthorized usb:1-1 transport_id:4\nXYZ weird\n"
    a, b = parse_devices_output(text)
    assert a.state is DeviceState.UNAUTHORIZED
    assert a.extra == {"usb": "1-1"}
    assert a.connection_type == "USB"
    assert not a.is_emulator_hint
    assert b.state is DeviceState.UNKNOWN
    assert b.raw_state == "weird"


def test_no_permissions_state_with_free_text():
    text = (
        "List of devices attached\n"
        "R58M123 no permissions (missing udev rules? user is in the plugdev group); "
        "see [http://developer.android.com/tools/device.html]\n"
    )
    [d] = parse_devices_output(text)
    assert d.state is DeviceState.NO_PERMISSIONS
    assert d.raw_state == "no permissions"


def test_duplicate_serials_deduplicated():
    text = "List of devices attached\nemulator-5554 device\nemulator-5554 device\n"
    assert len(parse_devices_output(text)) == 1


def test_windows_line_endings():
    text = DEVICES_ONE.replace("\n", "\r\n")
    assert parse_devices_output(text)[0].serial == "emulator-5554"


def test_getprop():
    props = parse_getprop_output(GETPROP_OUTPUT + "garbage line\n[empty]: []\n")
    assert props["ro.build.version.release"] == "13"
    assert props["ro.kernel.qemu"] == "1"
    assert props["empty"] == ""
    assert "garbage line" not in props


def test_wm_size_physical_and_override():
    phys, over = parse_wm_size("Physical size: 1080x1920\nOverride size: 720x1280\n")
    assert phys == (1080, 1920)
    assert over == (720, 1280)
    assert parse_wm_size("") == (None, None)


def test_adb_version():
    assert parse_adb_version("Android Debug Bridge version 1.0.41\nVersion 35.0.2-1\n") == "1.0.41 (35.0.2-1)"
    assert parse_adb_version("Android Debug Bridge version 1.0.32\n") == "1.0.32"
    assert parse_adb_version("some other program 2.0") is None
