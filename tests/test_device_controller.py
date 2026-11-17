from __future__ import annotations

import pytest

from app.core.device_controller import AdbStatus, DeviceController
from app.core.task_runner import TaskRunner
from app.emulator.adb_client import AdbClient, AdbNotFoundError, AdbTimeoutError
from app.emulator.adb_locator import AdbLocation
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_NONE, DEVICES_ONE, FakeRunner, standard_runner


def make_controller(config_manager, config, fake: FakeRunner, **kw) -> DeviceController:
    runner = TaskRunner()
    return DeviceController(
        config_manager,
        config,
        runner,
        client_factory=lambda path, timeout: AdbClient(path, runner=fake, timeout=timeout),
        **kw,
    )


def refresh_and_wait(qtbot, ctrl: DeviceController) -> None:
    with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda busy: busy is False, timeout=3000):
        assert ctrl.refresh_devices()


def test_no_adb_configured(qtbot, config_manager, config):
    config.adb_path = ""
    ctrl = make_controller(config_manager, config, standard_runner())
    assert ctrl.refresh_devices() is False
    assert ctrl.adb_status[0] is AdbStatus.NOT_CONFIGURED
    assert ctrl.devices == []


def test_no_devices(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_NONE))
    refresh_and_wait(qtbot, ctrl)
    assert ctrl.adb_status[0] is AdbStatus.OK
    assert ctrl.devices == []
    assert ctrl.selected_serial is None


def test_one_device_auto_selected_and_persisted(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_ONE))
    with qtbot.waitSignal(ctrl.selected_device_changed, timeout=3000) as sig:
        ctrl.refresh_devices()
    assert sig.args == ["emulator-5554"]
    assert ctrl.selected_device is not None and ctrl.selected_device.is_online
    assert config_manager.load().config.preferred_device_serial == "emulator-5554"


def test_multiple_devices_require_choice(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_MULTI))
    refresh_and_wait(qtbot, ctrl)
    assert len(ctrl.devices) == 3
    assert ctrl.selected_serial is None
    ctrl.select_device("127.0.0.1:5555")
    assert ctrl.selected_device.serial == "127.0.0.1:5555"


def test_preferred_device_restored_after_restart(qtbot, config_manager, config):
    config.preferred_device_serial = "127.0.0.1:5555"
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_MULTI))
    refresh_and_wait(qtbot, ctrl)
    assert ctrl.selected_serial == "127.0.0.1:5555"


def test_selected_device_disconnect(qtbot, config_manager, config):
    fake = standard_runner(DEVICES_MULTI)
    ctrl = make_controller(config_manager, config, fake)
    refresh_and_wait(qtbot, ctrl)
    ctrl.select_device("127.0.0.1:5555")
    fake.set(["devices", "-l"], DEVICES_ONE)  # 127.0.0.1:5555 disappeared
    refresh_and_wait(qtbot, ctrl)
    # Falls back to the single remaining online device, never to a stale entry.
    assert ctrl.selected_serial == "emulator-5554"


@pytest.mark.parametrize(
    "exc,status",
    [(AdbNotFoundError("gone"), AdbStatus.NOT_FOUND), (AdbTimeoutError("slow"), AdbStatus.TIMEOUT)],
)
def test_adb_failure_clears_devices(qtbot, config_manager, config, exc, status):
    fake = standard_runner(DEVICES_ONE)
    ctrl = make_controller(config_manager, config, fake)
    refresh_and_wait(qtbot, ctrl)
    assert ctrl.devices
    fake.responses[("devices", "-l")] = exc
    refresh_and_wait(qtbot, ctrl)
    assert ctrl.adb_status[0] is status
    assert ctrl.devices == []  # unknown state is not shown as connected
    assert ctrl.selected_serial is None


def test_nonzero_exit_sets_error(qtbot, config_manager, config):
    fake = FakeRunner()
    fake.set(["devices", "-l"], "", returncode=1, stderr="error: protocol fault")
    ctrl = make_controller(config_manager, config, fake)
    refresh_and_wait(qtbot, ctrl)
    assert ctrl.adb_status[0] is AdbStatus.ERROR
    assert "protocol fault" in ctrl.adb_status[1]


def test_overlapping_refresh_is_skipped(qtbot, config_manager, config):
    fake = standard_runner(DEVICES_ONE, delay=0.3)
    ctrl = make_controller(config_manager, config, fake)
    assert ctrl.refresh_devices() is True
    assert ctrl.refresh_devices() is False  # queued, not run concurrently
    assert ctrl.refresh_devices() is False  # coalesced with the queued request
    qtbot.waitUntil(lambda: fake.calls.count(("devices", "-l")) == 2, timeout=3000)
    qtbot.waitUntil(lambda: not ctrl.is_busy, timeout=3000)
    qtbot.wait(100)
    assert fake.calls.count(("devices", "-l")) == 2


def test_device_info(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_ONE))
    refresh_and_wait(qtbot, ctrl)
    with qtbot.waitSignal(ctrl.device_info_ready, timeout=3000) as sig:
        assert ctrl.fetch_device_info()
    info = sig.args[0]
    assert info.serial == "emulator-5554"
    assert info.android_version == "13"


def test_device_info_refused_for_offline(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(DEVICES_MULTI))
    refresh_and_wait(qtbot, ctrl)
    ctrl.select_device("127.0.0.1:5565")
    with qtbot.waitSignal(ctrl.operation_failed, timeout=1000):
        assert ctrl.fetch_device_info() is False


def test_connect_failure_reported(qtbot, config_manager, config):
    fake = standard_runner()
    fake.set(["connect", "127.0.0.1:5555"], "failed to connect to '127.0.0.1:5555': refused")
    ctrl = make_controller(config_manager, config, fake)
    with qtbot.waitSignal(ctrl.operation_failed, timeout=3000) as sig:
        ctrl.connect_address("127.0.0.1:5555")
    assert sig.args[0] == "Connect"
    assert config.recent_connect_addresses == []


def test_connect_success_remembers_address(qtbot, config_manager, config):
    fake = standard_runner()
    fake.set(["connect", "127.0.0.1:5555"], "connected to 127.0.0.1:5555")
    ctrl = make_controller(config_manager, config, fake)
    with qtbot.waitSignal(ctrl.operation_succeeded, timeout=3000):
        ctrl.connect_address("127.0.0.1:5555")
    assert config_manager.load().config.recent_connect_addresses == ["127.0.0.1:5555"]


def test_invalid_connect_address(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner())
    with qtbot.waitSignal(ctrl.operation_failed, timeout=3000) as sig:
        ctrl.connect_address("not an address")
    assert "host:port" in sig.args[1]


def test_restart_server_then_refresh(qtbot, config_manager, config):
    fake = standard_runner(DEVICES_ONE)
    ctrl = make_controller(config_manager, config, fake)
    with qtbot.waitSignal(ctrl.operation_succeeded, timeout=3000):
        ctrl.restart_adb_server()
    qtbot.waitUntil(lambda: ("devices", "-l") in fake.calls and not ctrl.is_busy, timeout=3000)
    assert fake.calls[:2] == [("kill-server",), ("start-server",)]


def test_auto_detect_sets_path(qtbot, config_manager, config):
    config.adb_path = ""
    loc = AdbLocation("/detected/adb", "System PATH", "1.0.41")
    ctrl = make_controller(config_manager, config, standard_runner(), locator=lambda _c: loc)
    with qtbot.waitSignal(ctrl.adb_path_changed, timeout=3000):
        ctrl.auto_detect_adb()
    assert config.adb_path == "/detected/adb"
    assert config_manager.load().config.adb_path == "/detected/adb"


def test_auto_detect_nothing_found(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner(), locator=lambda _c: None)
    with qtbot.waitSignal(ctrl.operation_failed, timeout=3000) as sig:
        ctrl.auto_detect_adb()
    assert "No working ADB" in sig.args[1]
    assert config.adb_path == "/fake/adb"  # unchanged


def test_launch_emulator_not_configured(qtbot, config_manager, config):
    ctrl = make_controller(config_manager, config, standard_runner())
    with qtbot.waitSignal(ctrl.operation_failed, timeout=3000) as sig:
        ctrl.launch_emulator()
    assert "not configured" in sig.args[1]


def test_auto_refresh_timer(qtbot, config_manager, config):
    config.auto_refresh_enabled = True
    config.auto_refresh_interval_s = 2
    ctrl = make_controller(config_manager, config, standard_runner())
    ctrl.apply_refresh_settings()
    assert ctrl._timer.isActive() and ctrl._timer.interval() == 2000
    config.auto_refresh_enabled = False
    ctrl.apply_refresh_settings()
    assert not ctrl._timer.isActive()
