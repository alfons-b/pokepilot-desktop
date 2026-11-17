from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.emulator.adb_client import AdbClient, AdbCommandError
from app.screen import mirror_controller as mc
from app.screen.mirror_controller import MirrorController, MirrorState
from tests.conftest import png_bytes
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_ONE, standard_runner


class BinaryFake:
    def __init__(self, data: bytes, code: int = 0) -> None:
        self.data, self.code, self.calls = data, code, []

    def __call__(self, args, timeout):
        self.calls.append(tuple(args[1:]))
        return self.code, self.data, "" if self.code == 0 else "error: device offline"


@pytest.fixture
def setup(qtbot, config_manager, config, fake_scrcpy_exe, monkeypatch, tmp_path):
    def factory(devices=DEVICES_ONE, binary=None, mode="run"):
        monkeypatch.setenv("FAKE_SCRCPY_MODE", mode)
        log = tmp_path / "scrcpy_calls.log"
        monkeypatch.setenv("FAKE_SCRCPY_LOG", str(log))
        config.scrcpy_path = str(fake_scrcpy_exe)
        fake = standard_runner(devices)
        bin_fake = binary or BinaryFake(png_bytes())
        runner = TaskRunner()
        ctrl = DeviceController(
            config_manager, config, runner,
            client_factory=lambda p, t: AdbClient(p, runner=fake, timeout=t, binary_runner=bin_fake),
        )
        mirror = MirrorController(ctrl, runner)
        with qtbot.waitSignal(ctrl.busy_changed, check_params_cb=lambda b: b is False, timeout=3000):
            ctrl.refresh_devices()
        created.append(mirror)
        return ctrl, mirror, log, bin_fake

    created: list[MirrorController] = []
    yield factory
    for m in created:
        m.shutdown()
    qtbot.wait(50)  # let deferred deletes run before objects are garbage-collected


def test_start_running_and_stop(qtbot, setup):
    ctrl, mirror, log, _ = setup()
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.RUNNING, timeout=8000):
        assert mirror.start()
    text = Path(log).read_text()
    assert "--serial=emulator-5554" in text
    assert "ADB=/fake/adb" in text  # scrcpy uses PokePilot's adb
    assert mirror.mirrored_serial == "emulator-5554"
    assert mirror.start() is False  # duplicate start refused
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.STOPPED, timeout=8000):
        mirror.stop()


def test_start_requires_device_and_path(qtbot, setup):
    ctrl, mirror, _, _ = setup(devices=DEVICES_MULTI)  # multiple -> nothing selected
    with qtbot.waitSignal(mirror.operation_failed, timeout=1000):
        assert mirror.start() is False
    ctrl.select_device("emulator-5554")
    ctrl.config.scrcpy_path = ""
    with qtbot.waitSignal(mirror.operation_failed, timeout=1000) as sig:
        assert mirror.start() is False
    assert "not configured" in sig.args[1]


def test_crash_reports_failure_and_auto_restarts(qtbot, setup, monkeypatch):
    monkeypatch.setattr(mc, "RESTART_DELAY_MS", 50)
    ctrl, mirror, log, _ = setup(mode="crash")
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.FAILED, timeout=8000) as sig:
        mirror.start()
    assert "Could not open video stream" in sig.args[1]
    # Auto restart up to MAX_RESTARTS, then gives up with an explicit error.
    with qtbot.waitSignal(mirror.operation_failed, timeout=15000) as sig2:
        pass
    assert "automatic restart disabled" in sig2.args[1]
    starts = Path(log).read_text().count("--serial=")
    assert starts == 1 + mc.MAX_RESTARTS


def test_crash_without_auto_restart(qtbot, setup):
    ctrl, mirror, log, _ = setup(mode="crash")
    ctrl.config.scrcpy_auto_restart = False
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.FAILED, timeout=8000):
        mirror.start()
    qtbot.wait(300)
    assert Path(log).read_text().count("--serial=") == 1


def test_silent_process_reported_unconfirmed(qtbot, setup, monkeypatch):
    ctrl, mirror, _, _ = setup(mode="silent")
    mirror.start()
    mirror._ready_timer.start(100)  # shorten the confirmation window for the test
    qtbot.waitUntil(lambda: mirror.state is MirrorState.RUNNING, timeout=5000)
    assert "not confirmed" in mirror.detail


def test_selection_change_stops_mirroring(qtbot, setup):
    ctrl, mirror, _, _ = setup(devices=DEVICES_MULTI)
    ctrl.select_device("emulator-5554")
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.RUNNING, timeout=8000):
        mirror.start()
    with qtbot.waitSignal(mirror.state_changed, check_params_cb=lambda s, d: s is MirrorState.STOPPED, timeout=8000):
        ctrl.select_device("127.0.0.1:5555")


def test_screenshot_saved(qtbot, setup):
    ctrl, mirror, _, bin_fake = setup()
    with qtbot.waitSignal(mirror.screenshot_saved, timeout=3000) as sig:
        mirror.capture_screenshot()
    path = Path(sig.args[0])
    assert path.exists() and path.parent == mc.screenshots_dir()
    assert QImage(str(path)).size().width() == 8
    assert bin_fake.calls[0] == ("-s", "emulator-5554", "exec-out", "screencap", "-p")


def test_screenshot_failure_reported(qtbot, setup):
    ctrl, mirror, _, _ = setup(binary=BinaryFake(b"", code=1))
    with qtbot.waitSignal(mirror.operation_failed, timeout=3000) as sig:
        mirror.capture_screenshot()
    assert "offline" in sig.args[1]


def test_screencap_validates_png():
    good = png_bytes()
    assert AdbClient("/a", binary_runner=BinaryFake(good)).screencap("s") == good
    crlf = good.replace(b"\n", b"\r\n")
    assert AdbClient("/a", binary_runner=BinaryFake(crlf)).screencap("s") == good
    with pytest.raises(AdbCommandError):
        AdbClient("/a", binary_runner=BinaryFake(b"not an image")).screencap("s")


def test_input_commands():
    r = standard_runner()
    r.set(["shell", "input", "tap", "10", "20"], "")
    r.set(["shell", "input", "swipe", "1", "2", "3", "4", "500"], "")
    r.set(["shell", "input", "keyevent", "4"], "")
    c = AdbClient("/a", runner=r)
    c.tap("s", 10, 20)
    c.swipe("s", 1, 2, 3, 4, 500)
    c.keyevent("s", 4)
    assert r.calls[-1] == ("-s", "s", "shell", "input", "keyevent", "4")
    r.set(["shell", "input", "tap", "1", "1"], "java.lang.SecurityException: Injecting input events requires...")
    with pytest.raises(AdbCommandError):
        c.tap("s", 1, 1)
