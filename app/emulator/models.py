"""Data models for ADB devices."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeviceState(StrEnum):
    """States reported by ``adb devices``."""

    DEVICE = "device"  # online and usable
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    AUTHORIZING = "authorizing"
    NO_PERMISSIONS = "no permissions"
    CONNECTING = "connecting"
    RECOVERY = "recovery"
    SIDELOAD = "sideload"
    BOOTLOADER = "bootloader"
    HOST = "host"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> DeviceState:
        raw = raw.strip().lower()
        for state in cls:
            if state.value == raw:
                return state
        return cls.UNKNOWN


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: DeviceState
    raw_state: str = ""
    product: str = ""
    model: str = ""
    device: str = ""
    transport_id: str = ""
    extra: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_online(self) -> bool:
        return self.state is DeviceState.DEVICE

    @property
    def is_network(self) -> bool:
        return ":" in self.serial

    @property
    def is_emulator_hint(self) -> bool:
        """Heuristic only: the serial looks like a local emulator instance.

        This is not proof. Real devices can be connected over loopback forwarding
        and some emulators use other serials; the UI labels this as a hint.
        """
        if self.serial.startswith("emulator-"):
            return True
        host = self.serial.rsplit(":", 1)[0] if self.is_network else ""
        return host in _LOOPBACK_HOSTS

    @property
    def connection_type(self) -> str:
        if self.serial.startswith("emulator-"):
            return "Emulator console"
        if self.is_network:
            return "TCP/IP"
        return "USB"

    @property
    def display_name(self) -> str:
        label = self.model.replace("_", " ") if self.model else self.serial
        return f"{label} ({self.serial})" if self.model else self.serial


@dataclass(frozen=True)
class DeviceInfo:
    """Properties read from a connected device via ``getprop`` and ``wm size``."""

    serial: str
    android_version: str = ""
    sdk_level: str = ""
    manufacturer: str = ""
    model: str = ""
    brand: str = ""
    abi: str = ""
    physical_resolution: tuple[int, int] | None = None
    override_resolution: tuple[int, int] | None = None
    qemu_flag: bool = False  # ro.kernel.qemu / ro.boot.qemu == "1"

    @property
    def effective_resolution(self) -> tuple[int, int] | None:
        return self.override_resolution or self.physical_resolution

    @staticmethod
    def format_resolution(res: tuple[int, int] | None) -> str:
        return f"{res[0]} x {res[1]}" if res else "Unknown"
