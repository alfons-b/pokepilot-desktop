"""DeviceController reconnect/instances and AppController behaviour."""

from __future__ import annotations

from app.core.app_controller import AppController
from app.core.device_controller import DeviceController
from app.core.task_runner import TaskRunner
from app.emulator.adb_client import AdbClient
from app.emulator.app_launcher import ProcessState
from app.emulator.instances import DiscoveryResult, EmulatorInstance
from tests.fakes.fake_runner import DEVICES_MULTI, DEVICES_NONE, DEVICES_ONE, TARGET_PKG, standard_runner

TCP = "127.0.0.1:5555"
DEVICES_TCP_OFFLINE = f"List of devices attached\n{TCP} offline\n"
DEVICES_TCP_ONLINE = f"List of devices attached\n{TCP} device product:x model:BlueStacks transport_id:9\n"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make(config_manager, config, fake, **kw):
    runner = TaskRunner()
    ctrl = DeviceController(
        config_manager,
        config,
        runner,
        client_factory=lambda p, t: AdbClient(p, runner=fake, timeout=t),
        **kw,
    )
    return ctrl, runner


def settle(qtbot, ctrl, runner) -> None:
    qtbot.waitUntil(lambda: not ctrl.is_busy and runner.active_count == 0, timeout=5000)


def test_auto_reconnect_missing_preferred_tcp_device(qtbot, config_manager, config):
    config.preferred_device_serial = TCP
    fake = standard_runner(DEVICES_NONE)
    fake.set(["connect", TCP], f"connected to {TCP}")
    ctrl, runner = make(config_manager, config, fake, clock=Clock())
    with qtbot.waitSignal(ctrl.reconnect_attempted, timeout=3000) as sig:
        ctrl.refresh_devices()
    assert sig.args == [TCP, True]
    qtbot.waitUntil(lambda: fake.calls.count(("devices", "-l")) >= 2, timeout=3000)  # refreshed after reconnect
    settle(qtbot, ctrl, runner)
    assert ("connect", TCP) in fake.calls


def test_auto_reconnect_offline_disconnects_first(qtbot, config_manager, config):
    config.preferred_device_serial = TCP
    fake = standard_runner(DEVICES_TCP_OFFLINE)
    fake.set(["disconnect", TCP], f"disconnected {TCP}")
    fake.set(["connect", TCP], f"connected to {TCP}")
    ctrl, runner = make(config_manager, config, fake, clock=Clock())
    ctrl.refresh_devices()
    qtbot.waitUntil(lambda: ("connect", TCP) in fake.calls, timeout=3000)
    assert fake.calls.index(("disconnect", TCP)) < fake.calls.index(("connect", TCP))
    settle(qtbot, ctrl, runner)


def test_auto_reconnect_rate_limited_and_disableable(qtbot, config_manager, config):
    config.preferred_device_serial = TCP
    fake = standard_runner(DEVICES_NONE)  # connect has no response -> fails
    clock = Clock()
    ctrl, runner = make(config_manager, config, fake, clock=clock)
    for _ in range(3):
        ctrl.refresh_devices()
        settle(qtbot, ctrl, runner)
    assert fake.calls.count(("connect", TCP)) == 1
    clock.t += 11
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    assert fake.calls.count(("connect", TCP)) == 2
    config.auto_reconnect_enabled = False
    clock.t += 11
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    assert fake.calls.count(("connect", TCP)) == 2


def test_no_reconnect_for_console_devices(qtbot, config_manager, config):
    config.preferred_device_serial = "emulator-5554"
    fake = standard_runner(DEVICES_NONE)
    ctrl, runner = make(config_manager, config, fake, clock=Clock())
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    assert not any(c[0] == "connect" for c in fake.calls)
    with qtbot.waitSignal(ctrl.operation_failed, timeout=1000):
        assert ctrl.reconnect_selected() is False


def test_manual_reconnect(qtbot, config_manager, config):
    fake = standard_runner(DEVICES_TCP_ONLINE)
    fake.set(["disconnect", TCP], "disconnected")
    fake.set(["connect", TCP], f"connected to {TCP}")
    ctrl, runner = make(config_manager, config, fake, clock=Clock())
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    assert ctrl.selected_serial == TCP
    with qtbot.waitSignal(ctrl.operation_succeeded, timeout=3000):
        assert ctrl.reconnect_selected()
    settle(qtbot, ctrl, runner)


def test_auto_select_does_not_overwrite_explicit_preference(qtbot, config_manager, config):
    config.preferred_device_serial = TCP
    fake = standard_runner(DEVICES_ONE)  # only emulator-5554 present
    config.auto_reconnect_enabled = False
    ctrl, runner = make(config_manager, config, fake)
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    assert ctrl.selected_serial == "emulator-5554"
    assert config.preferred_device_serial == TCP  # still remembered for reconnect


def test_discover_and_use_instance(qtbot, config_manager, config, tmp_path):
    exe = tmp_path / "HD-Player.exe"
    exe.write_text("")
    inst = EmulatorInstance("BlueStacks", "Pie64", "BlueStacks App Player", TCP, str(exe), ("--instance", "Pie64"), True)
    ctrl, runner = make(
        config_manager, config, standard_runner(), discoverer=lambda _c: DiscoveryResult([inst], [], ["x.conf"])
    )
    with qtbot.waitSignal(ctrl.instances_discovered, timeout=3000) as sig:
        ctrl.discover_instances()
    assert sig.args[0].instances == [inst]
    ctrl.use_instance_as_launcher(inst)
    saved = config_manager.load().config
    assert saved.emulator_path == str(exe)
    assert saved.emulator_args == "--instance Pie64"
    assert saved.preferred_device_serial == TCP
    settle(qtbot, ctrl, runner)


def test_launch_instance_without_executable(qtbot, config_manager, config):
    ctrl, _ = make(config_manager, config, standard_runner())
    inst = EmulatorInstance("BlueStacks", "Pie64", "Pie64", TCP)
    with qtbot.waitSignal(ctrl.operation_failed, timeout=1000):
        ctrl.launch_instance(inst)


# --------------------------------------------------------------- AppController
def make_apps(qtbot, config_manager, config, fake=None, devices=DEVICES_ONE):
    fake = fake or standard_runner(devices)
    ctrl, runner = make(config_manager, config, fake)
    apps = AppController(ctrl, runner)
    ctrl.refresh_devices()
    settle(qtbot, ctrl, runner)
    return ctrl, apps, fake


def test_apps_require_online_device(qtbot, config_manager, config):
    _, apps, _ = make_apps(qtbot, config_manager, config, devices=DEVICES_NONE)
    with qtbot.waitSignal(apps.operation_failed, timeout=1000) as sig:
        assert apps.load_packages() is False
    assert "online device" in sig.args[1]


def test_load_packages(qtbot, config_manager, config):
    _, apps, _ = make_apps(qtbot, config_manager, config)
    with qtbot.waitSignal(apps.packages_loaded, timeout=3000) as sig:
        apps.load_packages()
    assert sig.args[0] == "emulator-5554"
    assert TARGET_PKG in sig.args[1]


def test_set_target_validates_and_persists(qtbot, config_manager, config):
    _, apps, _ = make_apps(qtbot, config_manager, config)
    with qtbot.waitSignal(apps.operation_failed, timeout=1000):
        assert apps.set_target_package("not a package") is False
    assert apps.set_target_package(TARGET_PKG)
    assert config_manager.load().config.target_app_package == TARGET_PKG


def test_launch_target(qtbot, config_manager, config, monkeypatch):
    _, apps, _ = make_apps(qtbot, config_manager, config)
    with qtbot.waitSignal(apps.operation_failed, timeout=1000):
        apps.launch_target()  # no target yet
    apps.set_target_package(TARGET_PKG)
    with qtbot.waitSignal(apps.launch_finished, timeout=5000) as sig:
        apps.launch_target()
    assert sig.args[0].process_state is ProcessState.RUNNING


def test_stop_target_reports_actual_state(qtbot, config_manager, config):
    fake = standard_runner(DEVICES_ONE)
    _, apps, _ = make_apps(qtbot, config_manager, config, fake=fake)
    apps.set_target_package(TARGET_PKG)
    # pidof still reports the process after force-stop -> must not claim success
    with qtbot.waitSignal(apps.operation_failed, timeout=3000):
        apps.stop_target()
    fake.set(["shell", "pidof", TARGET_PKG], "", returncode=1)
    with qtbot.waitSignal(apps.operation_succeeded, timeout=3000):
        apps.stop_target()


def test_multi_device_apps_use_selected_serial(qtbot, config_manager, config):
    ctrl, apps, fake = make_apps(qtbot, config_manager, config, devices=DEVICES_MULTI)
    ctrl.select_device(TCP)
    with qtbot.waitSignal(apps.packages_loaded, timeout=3000):
        apps.load_packages()
    assert ("-s", TCP, "shell", "pm", "list", "packages", "-3") in fake.calls
