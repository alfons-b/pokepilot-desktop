import pytest

from app.emulator import app_launcher
from app.emulator.adb_client import AdbClient
from app.emulator.app_launcher import (
    ProcessState,
    parse_package_list,
    parse_ps_for_package,
    parse_resolve_activity,
    validate_package_name,
)
from tests.fakes.fake_runner import RESOLVE_OUTPUT, TARGET_PKG, standard_runner

SERIAL = "emulator-5554"


def client(runner):
    return AdbClient("/fake/adb", runner=runner)


def test_parse_package_list():
    text = "package:com.b\npackage:com.a\r\npackage:com.a\nnoise\npackage:\n"
    assert parse_package_list(text) == ["com.a", "com.b"]


def test_parse_resolve_activity():
    assert parse_resolve_activity(RESOLVE_OUTPUT) == f"{TARGET_PKG}/.MainActivity"
    assert parse_resolve_activity("No activity found") is None
    assert parse_resolve_activity("") is None


def test_parse_ps():
    ps = "USER PID PPID VSZ RSS WCHAN ADDR S NAME\nu0_a1 4242 1 0 0 0 0 S com.example.target\n"
    assert parse_ps_for_package(ps, TARGET_PKG)
    assert not parse_ps_for_package(ps, "com.other")


@pytest.mark.parametrize("name", ["com.nianticlabs.pokemongo", "a.b", "org.ex_ample.app2"])
def test_valid_package_names(name):
    assert validate_package_name(name) == name


@pytest.mark.parametrize("name", ["", "single", "com..x", "com.1abc", "com.x;rm", "com.x y", "-com.x"])
def test_invalid_package_names(name):
    with pytest.raises(ValueError):
        validate_package_name(name)


def test_list_packages_third_party_and_all():
    r = standard_runner()
    assert TARGET_PKG in app_launcher.list_packages(client(r), SERIAL)
    assert r.calls[-1] == ("-s", SERIAL, "shell", "pm", "list", "packages", "-3")
    assert "android" in app_launcher.list_packages(client(r), SERIAL, include_system=True)


def test_launch_success_verifies_process():
    r = standard_runner()
    result = app_launcher.launch_app(client(r), SERIAL, TARGET_PKG, sleep=lambda _s: None)
    assert result.command_accepted
    assert result.process_state is ProcessState.RUNNING
    assert "UI state not verified" in result.message
    assert ("-s", SERIAL, "shell", "am", "start", "-n", f"{TARGET_PKG}/.MainActivity") in r.calls


def test_launch_accepted_but_process_never_starts():
    r = standard_runner()
    r.set(["shell", "pidof", TARGET_PKG], "", returncode=1)
    sleeps = []
    result = app_launcher.launch_app(
        client(r), SERIAL, TARGET_PKG, verify_timeout_s=2, poll_interval_s=0.5, sleep=sleeps.append
    )
    assert result.command_accepted
    assert result.process_state is ProcessState.NOT_RUNNING
    assert "not running" in result.message
    assert sum(sleeps) >= 2


def test_launch_rejected_with_exit_zero_error():
    r = standard_runner()
    r.set(
        ["shell", "am", "start", "-n", f"{TARGET_PKG}/.MainActivity"],
        "Error: Activity class {com.example.target/.MainActivity} does not exist.",
    )
    result = app_launcher.launch_app(client(r), SERIAL, TARGET_PKG, sleep=lambda _s: None)
    assert not result.command_accepted
    assert "does not exist" in result.message


def test_launch_falls_back_to_monkey():
    r = standard_runner()
    r.set(["shell", "cmd", "package", "resolve-activity", "--brief", TARGET_PKG], "", returncode=255)
    r.set(
        ["shell", "monkey", "-p", TARGET_PKG, "-c", "android.intent.category.LAUNCHER", "1"],
        "Events injected: 1\n## Network stats: elapsed time=10ms",
    )
    result = app_launcher.launch_app(client(r), SERIAL, TARGET_PKG, sleep=lambda _s: None)
    assert result.command_accepted and result.activity is None
    assert result.process_state is ProcessState.RUNNING


def test_launch_monkey_failure():
    r = standard_runner()
    r.set(["shell", "cmd", "package", "resolve-activity", "--brief", "com.missing.app"], "No activity found")
    r.set(
        ["shell", "monkey", "-p", "com.missing.app", "-c", "android.intent.category.LAUNCHER", "1"],
        "** No activities found to run, monkey aborted.",
    )
    result = app_launcher.launch_app(client(r), SERIAL, "com.missing.app", sleep=lambda _s: None)
    assert not result.command_accepted
    assert "monkey aborted" in result.message


def test_process_state_pidof_missing_falls_back_to_ps():
    r = standard_runner()
    r.set(["shell", "pidof", TARGET_PKG], "", returncode=127, stderr="/system/bin/sh: pidof: not found")
    r.set(["shell", "ps"], f"USER PID NAME\nu0 1 {TARGET_PKG}\n")
    assert app_launcher.process_state(client(r), SERIAL, TARGET_PKG) is ProcessState.RUNNING
    r.set(["shell", "ps"], "", returncode=1, stderr="error")
    assert app_launcher.process_state(client(r), SERIAL, TARGET_PKG) is ProcessState.UNKNOWN


def test_force_stop_command():
    r = standard_runner()
    app_launcher.force_stop(client(r), SERIAL, TARGET_PKG)
    assert r.calls[-1] == ("-s", SERIAL, "shell", "am", "force-stop", TARGET_PKG)
