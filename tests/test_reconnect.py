from app.emulator.models import AdbDevice, DeviceState
from app.emulator.reconnect import is_tcp_address, plan_reconnect

TCP = "127.0.0.1:5555"


def test_is_tcp_address():
    assert is_tcp_address(TCP)
    assert not is_tcp_address("emulator-5554")
    assert not is_tcp_address(None)


def test_missing_tcp_device_is_connected():
    action = plan_reconnect([], None, TCP, None, now=100)
    assert action and action.address == TCP and not action.disconnect_first


def test_offline_tcp_device_disconnects_first():
    devices = [AdbDevice(TCP, DeviceState.OFFLINE)]
    action = plan_reconnect(devices, TCP, None, None, now=100)
    assert action and action.disconnect_first


def test_online_device_needs_nothing():
    assert plan_reconnect([AdbDevice(TCP, DeviceState.DEVICE)], TCP, TCP, None, now=100) is None


def test_non_tcp_never_reconnected():
    assert plan_reconnect([], "emulator-5554", None, None, now=100) is None
    assert plan_reconnect([], None, None, None, now=100) is None


def test_rate_limited():
    assert plan_reconnect([], TCP, None, last_attempt=95, now=100, interval=10) is None
    assert plan_reconnect([], TCP, None, last_attempt=89, now=100, interval=10) is not None


def test_selected_takes_priority_over_preferred():
    action = plan_reconnect([], "127.0.0.1:5565", TCP, None, now=0)
    assert action.address == "127.0.0.1:5565"
