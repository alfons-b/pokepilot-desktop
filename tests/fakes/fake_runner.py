"""In-memory CommandRunner double for AdbClient tests."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.emulator.adb_client import CommandResult

DEVICES_NONE = "List of devices attached\n\n"
DEVICES_ONE = (
    "List of devices attached\n"
    "emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 "
    "device:emu64xa transport_id:1\n\n"
)
DEVICES_MULTI = (
    "List of devices attached\n"
    "emulator-5554          device product:sdk_gphone64_x86_64 model:Pixel_7 device:emu64xa transport_id:1\n"
    "127.0.0.1:5555         device product:SM-S908E model:SM_S908E device:star2qltechn transport_id:2\n"
    "127.0.0.1:5565         offline transport_id:3\n\n"
)
VERSION_OUTPUT = (
    "Android Debug Bridge version 1.0.41\nVersion 35.0.2-12147458\nInstalled as /fake/adb\n"
)
GETPROP_OUTPUT = (
    "[ro.build.version.release]: [13]\n"
    "[ro.build.version.sdk]: [33]\n"
    "[ro.product.manufacturer]: [Google]\n"
    "[ro.product.model]: [sdk_gphone64_x86_64]\n"
    "[ro.product.brand]: [google]\n"
    "[ro.product.cpu.abi]: [x86_64]\n"
    "[ro.kernel.qemu]: [1]\n"
)
WM_SIZE_OUTPUT = "Physical size: 1080x2400\n"
TARGET_PKG = "com.example.target"
PACKAGES_3RD = f"package:{TARGET_PKG}\npackage:com.android.chrome\npackage:org.example.notes\n"
PACKAGES_ALL = PACKAGES_3RD + "package:android\npackage:com.android.settings\n"
RESOLVE_OUTPUT = f"priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=false\n{TARGET_PKG}/.MainActivity\n"
AM_START_OUTPUT = f"Starting: Intent {{ cmp={TARGET_PKG}/.MainActivity }}\n"


class FakeRunner:
    """Maps argument tuples (without the adb path) to results or exceptions."""

    def __init__(self, responses: dict[tuple[str, ...], object] | None = None, delay: float = 0.0) -> None:
        self.responses: dict[tuple[str, ...], object] = dict(responses or {})
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []
        self.delay = delay
        self.input_ok = False  # accept any "shell input ..." command

    def set(self, args: Sequence[str], stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.responses[tuple(args)] = (stdout, returncode, stderr)

    def __call__(self, args: Sequence[str], timeout: float) -> CommandResult:
        argv = tuple(args)
        key = argv[1:]
        self.calls.append(key)
        self.timeouts.append(timeout)
        if self.delay:
            time.sleep(self.delay)
        resp = self.responses.get(key)
        if resp is None:
            # Match ignoring a leading "-s SERIAL" pair.
            if len(key) > 2 and key[0] == "-s":
                resp = self.responses.get(key[2:])
        stripped = key[2:] if len(key) > 2 and key[0] == "-s" else key
        if resp is None and self.input_ok and stripped[:2] == ("shell", "input"):
            resp = ("", 0, "")
        if resp is None:
            return CommandResult(argv, 1, "", f"fake: no response for {key}")
        if isinstance(resp, BaseException):
            raise resp
        stdout, code, stderr = resp  # type: ignore[misc]
        return CommandResult(argv, code, stdout, stderr)


def standard_runner(devices_output: str = DEVICES_ONE, delay: float = 0.0) -> FakeRunner:
    r = FakeRunner(delay=delay)
    r.set(["version"], VERSION_OUTPUT)
    r.set(["devices", "-l"], devices_output)
    r.set(["shell", "getprop"], GETPROP_OUTPUT)
    r.set(["shell", "wm", "size"], WM_SIZE_OUTPUT)
    r.set(["kill-server"], "")
    r.set(["start-server"], "* daemon started successfully\n")
    r.set(["shell", "pm", "list", "packages", "-3"], PACKAGES_3RD)
    r.set(["shell", "pm", "list", "packages"], PACKAGES_ALL)
    r.set(["shell", "cmd", "package", "resolve-activity", "--brief", TARGET_PKG], RESOLVE_OUTPUT)
    r.set(["shell", "am", "start", "-n", f"{TARGET_PKG}/.MainActivity"], AM_START_OUTPUT)
    r.set(["shell", "pidof", TARGET_PKG], "4242\n")
    r.set(["shell", "am", "force-stop", TARGET_PKG], "")
    r.set(["get-state"], "device\n")
    r.input_ok = True
    return r
