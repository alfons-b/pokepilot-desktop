"""Launch an installed Android app and check whether its process is running.

Results distinguish three facts that must not be conflated:

* the launch *command* was accepted by Android,
* the app *process* is running (``pidof``),
* the app's UI is in a particular state - this module never claims that;
  UI verification is done separately (app.pgsharp).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.emulator.adb_client import AdbClient, AdbCommandError

logger = logging.getLogger(__name__)


class ProcessState(StrEnum):
    RUNNING = "Running"
    NOT_RUNNING = "Not running"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class LaunchResult:
    package: str
    activity: str | None
    command_accepted: bool
    process_state: ProcessState
    message: str


def parse_package_list(text: str) -> list[str]:
    """Parse ``pm list packages`` output (``package:com.example``)."""
    pkgs = {line.strip()[len("package:"):].strip() for line in text.splitlines() if line.strip().startswith("package:")}
    return sorted(p for p in pkgs if p)


def parse_resolve_activity(text: str) -> str | None:
    """Parse ``cmd package resolve-activity --brief`` -> ``pkg/.Activity`` or None."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if "/" in line and " " not in line:
            return line
    return None


def parse_ps_for_package(text: str, package: str) -> bool:
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[-1] == package:
            return True
    return False


def validate_package_name(package: str) -> str:
    package = package.strip()
    parts = package.split(".")
    if len(parts) < 2 or not all(p and (p[0].isalpha() or p[0] == "_") and p.replace("_", "a").isalnum() for p in parts):
        raise ValueError(f"'{package}' is not a valid Android package name.")
    return package


def list_packages(client: AdbClient, serial: str, include_system: bool = False) -> list[str]:
    args = ["shell", "pm", "list", "packages"]
    if not include_system:
        args.append("-3")
    return parse_package_list(client.run(args, serial=serial).stdout)


def process_state(client: AdbClient, serial: str, package: str) -> ProcessState:
    package = validate_package_name(package)
    res = client.run(["shell", "pidof", package], serial=serial, check=False)
    out = res.output.lower()
    if res.returncode == 0 and res.stdout.strip():
        return ProcessState.RUNNING
    if "not found" not in out and "inaccessible" not in out:
        return ProcessState.NOT_RUNNING
    # Very old Android without pidof: fall back to ps.
    try:
        ps = client.run(["shell", "ps"], serial=serial)
    except AdbCommandError:
        return ProcessState.UNKNOWN
    return ProcessState.RUNNING if parse_ps_for_package(ps.stdout, package) else ProcessState.NOT_RUNNING


def launch_app(
    client: AdbClient,
    serial: str,
    package: str,
    verify_timeout_s: float = 10.0,
    poll_interval_s: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> LaunchResult:
    package = validate_package_name(package)
    activity = parse_resolve_activity(
        client.run(["shell", "cmd", "package", "resolve-activity", "--brief", package], serial=serial, check=False).stdout
    )
    if activity:
        res = client.run(["shell", "am", "start", "-n", activity], serial=serial, check=False)
        accepted = res.returncode == 0 and "error" not in res.output.lower()
    else:
        # Fallback for Android versions without resolve-activity.
        res = client.run(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            serial=serial,
            check=False,
        )
        accepted = "events injected: 1" in res.output.lower()
    if not accepted:
        detail = res.output.strip().splitlines()[-1] if res.output.strip() else "no output"
        return LaunchResult(package, activity, False, ProcessState.UNKNOWN, f"Android rejected the launch: {detail}")

    state = ProcessState.UNKNOWN
    waited = 0.0
    while waited <= verify_timeout_s:
        state = process_state(client, serial, package)
        if state is ProcessState.RUNNING:
            break
        sleep(poll_interval_s)
        waited += poll_interval_s
    if state is ProcessState.RUNNING:
        msg = f"{package} launched; process is running. (UI state not verified.)"
    elif state is ProcessState.NOT_RUNNING:
        msg = f"Launch command accepted, but {package} is not running after {verify_timeout_s:.0f}s."
    else:
        msg = "Launch command accepted; process state could not be determined."
    logger.info(msg)
    return LaunchResult(package, activity, True, state, msg)


def is_installed(client: AdbClient, serial: str, package: str) -> bool:
    res = client.run(["shell", "pm", "path", validate_package_name(package)], serial=serial, check=False)
    return res.returncode == 0 and res.stdout.strip().startswith("package:")


def force_stop(client: AdbClient, serial: str, package: str) -> None:
    client.run(["shell", "am", "force-stop", validate_package_name(package)], serial=serial)
