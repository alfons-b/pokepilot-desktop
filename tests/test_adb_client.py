import pytest

from app.emulator.adb_client import (
    AdbClient,
    AdbCommandError,
    AdbNotConfiguredError,
    AdbNotFoundError,
    AdbTimeoutError,
    subprocess_runner,
    validate_address,
)
from tests.fakes.fake_runner import DEVICES_MULTI, FakeRunner, standard_runner


def test_not_configured():
    with pytest.raises(AdbNotConfiguredError):
        AdbClient("", runner=FakeRunner()).list_devices()


def test_list_devices_uses_argument_list():
    runner = standard_runner(DEVICES_MULTI)
    devices = AdbClient("/fake/adb", runner=runner).list_devices()
    assert len(devices) == 3
    assert runner.calls == [("devices", "-l")]


def test_device_commands_pin_serial():
    runner = standard_runner()
    info = AdbClient("/fake/adb", runner=runner).get_device_info("emulator-5554")
    assert runner.calls[0] == ("-s", "emulator-5554", "shell", "getprop")
    assert runner.calls[1] == ("-s", "emulator-5554", "shell", "wm", "size")
    assert info.android_version == "13"
    assert info.sdk_level == "33"
    assert info.physical_resolution == (1080, 2400)
    assert info.effective_resolution == (1080, 2400)
    assert info.qemu_flag is True


def test_device_info_requires_serial():
    with pytest.raises(ValueError):
        AdbClient("/fake/adb", runner=standard_runner()).get_device_info("")


def test_empty_getprop_is_error():
    runner = standard_runner()
    runner.set(["shell", "getprop"], "")
    with pytest.raises(AdbCommandError):
        AdbClient("/fake/adb", runner=runner).get_device_info("emulator-5554")


def test_nonzero_exit_raises_with_output():
    runner = FakeRunner()
    runner.set(["devices", "-l"], "", returncode=1, stderr="error: protocol fault")
    with pytest.raises(AdbCommandError, match="protocol fault"):
        AdbClient("/fake/adb", runner=runner).list_devices()


def test_runner_exceptions_propagate():
    runner = FakeRunner({("devices", "-l"): AdbTimeoutError("slow")})
    with pytest.raises(AdbTimeoutError):
        AdbClient("/fake/adb", runner=runner).list_devices()


def test_version_rejects_non_adb_binary():
    runner = FakeRunner()
    runner.set(["version"], "Notepad 1.0")
    with pytest.raises(AdbCommandError, match="did not identify"):
        AdbClient("/fake/notepad", runner=runner).version()


def test_connect_success_and_failure_text():
    runner = FakeRunner()
    runner.set(["connect", "127.0.0.1:5555"], "connected to 127.0.0.1:5555")
    runner.set(["connect", "127.0.0.1:5556"], "already connected to 127.0.0.1:5556")
    runner.set(["connect", "127.0.0.1:5557"], "failed to connect to '127.0.0.1:5557': Connection refused")
    runner.set(["connect", "127.0.0.1:5558"], "cannot connect to 127.0.0.1:5558: No connection")
    client = AdbClient("/fake/adb", runner=runner)
    assert "connected" in client.connect("127.0.0.1:5555")
    assert "already" in client.connect("127.0.0.1:5556")
    with pytest.raises(AdbCommandError):
        client.connect("127.0.0.1:5557")  # exit code 0 but failure text
    with pytest.raises(AdbCommandError):
        client.connect("127.0.0.1:5558")


@pytest.mark.parametrize("addr", ["127.0.0.1:5555", "localhost:7555", "my-pc.local:16384", " 10.0.0.2:62001 "])
def test_valid_addresses(addr):
    assert validate_address(addr) == addr.strip()


@pytest.mark.parametrize(
    "addr", ["", "127.0.0.1", "127.0.0.1:", "127.0.0.1:99999", "300.1.1.1:5555", "a b:5555", "1.2.3.4:0", "x;rm:5"]
)
def test_invalid_addresses(addr):
    with pytest.raises(ValueError):
        validate_address(addr)


def test_connect_validates_before_running():
    runner = FakeRunner()
    with pytest.raises(ValueError):
        AdbClient("/fake/adb", runner=runner).connect("bad address")
    assert runner.calls == []


def test_restart_server_tolerates_kill_failure():
    runner = standard_runner()
    runner.set(["kill-server"], "", returncode=1, stderr="cannot connect to daemon")
    AdbClient("/fake/adb", runner=runner).restart_server()
    assert runner.calls == [("kill-server",), ("start-server",)]


def test_subprocess_runner_missing_executable(tmp_path):
    with pytest.raises(AdbNotFoundError):
        subprocess_runner([str(tmp_path / "does-not-exist-adb")], 5)
