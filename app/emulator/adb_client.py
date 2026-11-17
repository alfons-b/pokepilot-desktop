"""Synchronous ADB client. Always call from a background worker, never the GUI thread.

All commands are built as argument lists (no shell interpolation) and every
device-specific command is pinned to an explicit serial with ``-s``.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.emulator.adb_parser import (
    parse_adb_version,
    parse_devices_output,
    parse_getprop_output,
    parse_wm_size,
)
from app.emulator.models import AdbDevice, DeviceInfo

logger = logging.getLogger(__name__)

_ADDRESS_RE = re.compile(
    r"^(?P<host>(?:\d{1,3}(?:\.\d{1,3}){3})|localhost|[A-Za-z0-9](?:[A-Za-z0-9\-.]*[A-Za-z0-9])?)"
    r":(?P<port>\d{1,5})$"
)


class AdbError(Exception):
    """Base ADB failure."""


class AdbNotConfiguredError(AdbError):
    """No ADB executable path is configured."""


class AdbNotFoundError(AdbError):
    """The configured ADB executable does not exist or cannot be executed."""


class AdbTimeoutError(AdbError):
    """An ADB command exceeded its timeout."""


class AdbCommandError(AdbError):
    """ADB returned a non-zero exit code or reported a failure."""

    def __init__(self, message: str, result: CommandResult | None = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


CommandRunner = Callable[[Sequence[str], float], CommandResult]
# Returns (returncode, stdout bytes, stderr text) for binary output such as screenshots.
BinaryRunner = Callable[[Sequence[str], float], tuple[int, bytes, str]]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0


def subprocess_runner(args: Sequence[str], timeout: float) -> CommandResult:
    """Default runner: executes a command without a shell and without a console window."""
    argv = [str(a) for a in args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=_no_window_flags(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise AdbNotFoundError(f"Executable not found: {argv[0]}") from exc
    except PermissionError as exc:
        raise AdbNotFoundError(f"Executable is not runnable: {argv[0]} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeoutError(f"Command timed out after {timeout:.0f}s: {' '.join(argv[1:])}") from exc
    except OSError as exc:
        raise AdbError(f"Failed to run {argv[0]}: {exc}") from exc
    return CommandResult(tuple(argv), proc.returncode, proc.stdout or "", proc.stderr or "")


def subprocess_binary_runner(args: Sequence[str], timeout: float) -> tuple[int, bytes, str]:
    argv = [str(a) for a in args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=_no_window_flags(),
            check=False,
        )
    except FileNotFoundError as exc:
        raise AdbNotFoundError(f"Executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbTimeoutError(f"Command timed out after {timeout:.0f}s: {' '.join(argv[1:])}") from exc
    except OSError as exc:
        raise AdbError(f"Failed to run {argv[0]}: {exc}") from exc
    return proc.returncode, proc.stdout or b"", (proc.stderr or b"").decode("utf-8", "replace")


def validate_address(address: str) -> str:
    """Validate a ``host:port`` address for ``adb connect``. Returns the stripped address."""
    address = address.strip()
    m = _ADDRESS_RE.match(address)
    if not m:
        raise ValueError(f"'{address}' is not a valid host:port address (example: 127.0.0.1:5555).")
    port = int(m.group("port"))
    if not 1 <= port <= 65535:
        raise ValueError(f"Port {port} is out of range (1-65535).")
    host = m.group("host")
    if re.fullmatch(r"[\d.]+", host) and any(int(o) > 255 for o in host.split(".")):
        raise ValueError(f"'{host}' is not a valid IPv4 address.")
    return address


class AdbClient:
    def __init__(
        self,
        adb_path: str,
        runner: CommandRunner = subprocess_runner,
        timeout: float = 10.0,
        binary_runner: BinaryRunner = subprocess_binary_runner,
    ) -> None:
        self.adb_path = (adb_path or "").strip()
        self._runner = runner
        self._binary_runner = binary_runner
        self.timeout = timeout

    # ------------------------------------------------------------------ core
    def run(
        self,
        args: Sequence[str],
        serial: str | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        if not self.adb_path:
            raise AdbNotConfiguredError("ADB path is not configured. Set it in Settings.")
        argv: list[str] = [self.adb_path]
        if serial:
            argv += ["-s", serial]
        argv += list(args)
        logger.debug("adb %s", " ".join(argv[1:]))
        result = self._runner(argv, timeout if timeout is not None else self.timeout)
        if check and result.returncode != 0:
            detail = result.output or f"exit code {result.returncode}"
            raise AdbCommandError(f"adb {' '.join(args)} failed: {detail}", result)
        return result

    # --------------------------------------------------------------- server
    def version(self) -> str:
        result = self.run(["version"])
        version = parse_adb_version(result.stdout)
        if version is None:
            raise AdbCommandError(
                f"'{self.adb_path}' did not identify itself as Android Debug Bridge.", result
            )
        return version

    def start_server(self) -> None:
        self.run(["start-server"], timeout=max(self.timeout, 20.0))

    def kill_server(self) -> None:
        # kill-server returns non-zero if no server is running; that is not an error.
        self.run(["kill-server"], check=False)

    def restart_server(self) -> None:
        logger.info("Restarting ADB server")
        self.kill_server()
        self.start_server()

    # -------------------------------------------------------------- devices
    def list_devices(self) -> list[AdbDevice]:
        # First call may start the daemon, which can take several seconds.
        result = self.run(["devices", "-l"], timeout=max(self.timeout, 20.0))
        return parse_devices_output(result.stdout)

    def connect(self, address: str) -> str:
        address = validate_address(address)
        result = self.run(["connect", address], check=False)
        text = result.output
        lower = text.lower()
        # adb connect frequently exits 0 on failure, so the message is authoritative.
        if "connected to" in lower and "cannot" not in lower and "failed" not in lower:
            return text
        raise AdbCommandError(f"Could not connect to {address}: {text or 'no output'}", result)

    def disconnect(self, address: str) -> str:
        address = validate_address(address)
        result = self.run(["disconnect", address], check=False)
        if result.returncode != 0 or "error" in result.output.lower():
            raise AdbCommandError(f"Could not disconnect {address}: {result.output}", result)
        return result.output

    def get_device_info(self, serial: str) -> DeviceInfo:
        if not serial:
            raise ValueError("A device serial is required.")
        props = parse_getprop_output(self.run(["shell", "getprop"], serial=serial).stdout)
        if not props:
            raise AdbCommandError(f"Device {serial} returned no system properties.")
        physical, override = parse_wm_size(self.run(["shell", "wm", "size"], serial=serial, check=False).stdout)
        return DeviceInfo(
            serial=serial,
            android_version=props.get("ro.build.version.release", ""),
            sdk_level=props.get("ro.build.version.sdk", ""),
            manufacturer=props.get("ro.product.manufacturer", ""),
            model=props.get("ro.product.model", ""),
            brand=props.get("ro.product.brand", ""),
            abi=props.get("ro.product.cpu.abi", ""),
            physical_resolution=physical,
            override_resolution=override,
            qemu_flag=props.get("ro.kernel.qemu") == "1" or props.get("ro.boot.qemu") == "1",
        )

    # ---------------------------------------------------------- screen/input
    def screencap(self, serial: str) -> bytes:
        """Capture the device screen as PNG bytes (``adb exec-out screencap -p``)."""
        if not self.adb_path:
            raise AdbNotConfiguredError("ADB path is not configured. Set it in Settings.")
        if not serial:
            raise ValueError("A device serial is required.")
        argv = [self.adb_path, "-s", serial, "exec-out", "screencap", "-p"]
        code, data, err = self._binary_runner(argv, max(self.timeout, 15.0))
        if code != 0:
            raise AdbCommandError(f"screencap failed on {serial}: {err.strip() or f'exit code {code}'}")
        if not data.startswith(PNG_SIGNATURE):
            # Some old devices translate \n to \r\n on the shell transport.
            fixed = data.replace(b"\r\n", b"\n")
            if fixed.startswith(PNG_SIGNATURE):
                return fixed
            raise AdbCommandError(f"screencap on {serial} did not return a PNG image ({len(data)} bytes).")
        return data

    def tap(self, serial: str, x: int, y: int) -> None:
        self._input(serial, ["tap", str(int(x)), str(int(y))])

    def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._input(serial, ["swipe", *(str(int(v)) for v in (x1, y1, x2, y2, duration_ms))])

    def keyevent(self, serial: str, keycode: int) -> None:
        self._input(serial, ["keyevent", str(int(keycode))])

    def get_state(self, serial: str) -> str:
        """Return the transport state ('device', 'offline', ...) or raise if the device is unknown."""
        return self.run(["get-state"], serial=serial).stdout.strip()

    def _input(self, serial: str, args: list[str]) -> None:
        if not serial:
            raise ValueError("A device serial is required.")
        res = self.run(["shell", "input", *args], serial=serial)
        # 'input' prints usage/errors on stdout with exit code 0 on some Android versions.
        if "error" in res.output.lower() or "exception" in res.output.lower():
            raise AdbCommandError(f"input {' '.join(args)} failed: {res.output}", res)


KEYCODE_BACK = 4
KEYCODE_HOME = 3
