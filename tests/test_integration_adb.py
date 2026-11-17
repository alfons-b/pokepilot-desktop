"""Integration tests: real subprocess execution against a fake adb executable."""

from __future__ import annotations

import pytest

from app.core.device_controller import AdbStatus, DeviceController
from app.core.task_runner import TaskRunner
from app.emulator.adb_client import AdbClient, AdbCommandError, AdbTimeoutError
from app.emulator.adb_locator import AdbCandidate, locate_adb


@pytest.mark.parametrize("scenario,count", [("none", 0), ("one", 1), ("multi", 3)])
def test_list_devices_via_subprocess(fake_adb_exe, monkeypatch, scenario, count):
    monkeypatch.setenv("FAKE_ADB_SCENARIO", scenario)
    assert len(AdbClient(str(fake_adb_exe)).list_devices()) == count


def test_adb_failure_via_subprocess(fake_adb_exe, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_SCENARIO", "fail")
    with pytest.raises(AdbCommandError, match="protocol fault"):
        AdbClient(str(fake_adb_exe)).list_devices()


def test_adb_hang_times_out(fake_adb_exe, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_SCENARIO", "hang")
    with pytest.raises(AdbTimeoutError):
        AdbClient(str(fake_adb_exe), timeout=1).run(["get-state"], timeout=1)


def test_connect_exit_zero_failure_detected(fake_adb_exe, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_SCENARIO", "one")
    with pytest.raises(AdbCommandError, match="Connection refused"):
        AdbClient(str(fake_adb_exe)).connect("127.0.0.1:5555")


def test_device_info_via_subprocess(fake_adb_exe, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_SCENARIO", "one")
    info = AdbClient(str(fake_adb_exe)).get_device_info("emulator-5554")
    assert info.android_version == "13"
    assert info.physical_resolution == (1080, 2400)


def test_locate_real_fake_adb(fake_adb_exe):
    loc = locate_adb(candidates=[AdbCandidate(str(fake_adb_exe), "test")])
    assert loc is not None and loc.version.startswith("1.0.41")


def test_controller_end_to_end_emulator_restart(qtbot, fake_adb_exe, monkeypatch, config_manager, config):
    """Device present -> emulator stops (no devices) -> emulator returns."""
    config.adb_path = str(fake_adb_exe)
    ctrl = DeviceController(config_manager, config, TaskRunner())

    def refresh():
        with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=10000):
            ctrl.refresh_devices()

    monkeypatch.setenv("FAKE_ADB_SCENARIO", "one")
    refresh()
    assert ctrl.selected_serial == "emulator-5554"

    monkeypatch.setenv("FAKE_ADB_SCENARIO", "none")
    refresh()
    assert ctrl.devices == [] and ctrl.selected_serial is None
    assert ctrl.adb_status[0] is AdbStatus.OK

    monkeypatch.setenv("FAKE_ADB_SCENARIO", "one")
    refresh()
    assert ctrl.selected_serial == "emulator-5554"  # restored via preferred serial

    monkeypatch.setenv("FAKE_ADB_SCENARIO", "fail")
    refresh()
    assert ctrl.adb_status[0] is AdbStatus.ERROR and ctrl.devices == []


def test_controller_missing_adb_executable(qtbot, tmp_path, config_manager, config):
    config.adb_path = str(tmp_path / "no-such-adb")
    ctrl = DeviceController(config_manager, config, TaskRunner())
    with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=5000):
        ctrl.refresh_devices()
    assert ctrl.adb_status[0] is AdbStatus.NOT_FOUND


def test_app_list_and_launch_via_subprocess(fake_adb_exe, monkeypatch):
    from app.emulator import app_launcher
    from app.emulator.app_launcher import ProcessState
    from tests.fakes.fake_runner import TARGET_PKG

    monkeypatch.setenv("FAKE_ADB_SCENARIO", "one")
    client = AdbClient(str(fake_adb_exe))
    assert TARGET_PKG in app_launcher.list_packages(client, "emulator-5554")
    result = app_launcher.launch_app(client, "emulator-5554", TARGET_PKG)
    assert result.command_accepted and result.process_state is ProcessState.RUNNING
    assert app_launcher.process_state(client, "emulator-5554", "com.not.running") is ProcessState.NOT_RUNNING
