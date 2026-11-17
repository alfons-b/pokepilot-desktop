"""Emulator instances discovered from an emulator's own configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmulatorInstance:
    provider: str  # e.g. "BlueStacks"
    name: str  # internal instance id, e.g. "Pie64"
    display_name: str
    adb_address: str | None  # "127.0.0.1:5555" when known
    launch_executable: str | None = None
    launch_args: tuple[str, ...] = ()
    adb_enabled: bool | None = None  # None = unknown

    @property
    def can_launch(self) -> bool:
        return bool(self.launch_executable)


@dataclass
class DiscoveryResult:
    instances: list[EmulatorInstance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # files that were read
