"""JSON configuration with validation, corruption recovery and atomic saves."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_SCHEMA_VERSION = 1
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_RECENT_ADDRESSES = 10

# (min, max) inclusive ranges for numeric settings.
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "adb_command_timeout_s": (1.0, 120.0),
    "auto_refresh_interval_s": (2, 300),
    "scrcpy_max_size": (0, 4096),
    "scrcpy_max_fps": (1, 120),
    "scrcpy_bitrate_mbps": (1, 100),
}


@dataclass
class AppConfig:
    """All persisted user settings. Never store game credentials here."""

    schema_version: int = CONFIG_SCHEMA_VERSION
    adb_path: str = ""
    adb_command_timeout_s: float = 10.0
    auto_refresh_enabled: bool = True
    auto_refresh_interval_s: int = 5
    preferred_device_serial: str = ""
    auto_reconnect_enabled: bool = True
    target_app_package: str = ""
    bluestacks_conf_path: str = ""
    recent_connect_addresses: list[str] = field(default_factory=list)
    emulator_path: str = ""
    emulator_args: str = ""
    scrcpy_path: str = ""
    scrcpy_max_size: int = 1280
    scrcpy_max_fps: int = 30
    scrcpy_bitrate_mbps: int = 8
    scrcpy_fullscreen: bool = False
    scrcpy_always_on_top: bool = False
    scrcpy_stay_awake: bool = True
    scrcpy_view_only: bool = False
    scrcpy_uhid_keyboard: bool = False
    scrcpy_auto_restart: bool = True
    log_level: str = "INFO"
    window_geometry: str = ""

    def normalize(self) -> list[str]:
        """Clamp/repair values in place. Returns human-readable warnings."""
        warnings: list[str] = []
        for name, (lo, hi) in NUMERIC_RANGES.items():
            value = getattr(self, name)
            if value < lo or value > hi:
                clamped = type(value)(min(max(value, lo), hi))
                warnings.append(f"'{name}'={value} out of range [{lo}, {hi}]; using {clamped}.")
                setattr(self, name, clamped)
        level = self.log_level.upper()
        if level not in VALID_LOG_LEVELS:
            warnings.append(f"Unknown log level '{self.log_level}'; using INFO.")
            level = "INFO"
        self.log_level = level
        self.adb_path = self.adb_path.strip()
        self.emulator_path = self.emulator_path.strip()
        self.scrcpy_path = self.scrcpy_path.strip()
        self.target_app_package = self.target_app_package.strip()
        self.bluestacks_conf_path = self.bluestacks_conf_path.strip()
        self.recent_connect_addresses = list(
            dict.fromkeys(a.strip() for a in self.recent_connect_addresses if a.strip())
        )[:MAX_RECENT_ADDRESSES]
        self.schema_version = CONFIG_SCHEMA_VERSION
        return warnings

    def remember_address(self, address: str) -> None:
        address = address.strip()
        if not address:
            return
        items = [a for a in self.recent_connect_addresses if a != address]
        self.recent_connect_addresses = [address, *items][:MAX_RECENT_ADDRESSES]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> tuple[AppConfig, list[str]]:
        """Build a config from untrusted data, skipping invalid fields with warnings."""
        warnings: list[str] = []
        defaults = cls()
        kwargs: dict[str, Any] = {}
        known = {f.name for f in fields(cls)}
        for key in data:
            if key not in known:
                warnings.append(f"Ignoring unknown setting '{key}'.")
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            expected = type(getattr(defaults, f.name))
            if expected is float and type(value) is int:
                value = float(value)
            if expected is list:
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    warnings.append(f"Setting '{f.name}' must be a list of strings; using default.")
                    continue
            elif type(value) is not expected:  # strict: bool is not accepted as int
                warnings.append(
                    f"Setting '{f.name}' has type {type(value).__name__}, expected "
                    f"{expected.__name__}; using default."
                )
                continue
            kwargs[f.name] = value
        config = cls(**kwargs)
        warnings.extend(config.normalize())
        return config, warnings


@dataclass
class ConfigLoadResult:
    config: AppConfig
    warnings: list[str] = field(default_factory=list)
    recovered_from_corruption: bool = False
    backup_path: Path | None = None


class ConfigManager:
    """Loads and saves :class:`AppConfig` to a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> ConfigLoadResult:
        if not self.path.exists():
            logger.info("No configuration at %s; using defaults.", self.path)
            return ConfigLoadResult(AppConfig())
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("configuration root must be a JSON object")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            backup = self._backup_corrupt_file()
            msg = f"Configuration file was unreadable ({exc}). Defaults loaded."
            if backup:
                msg += f" The broken file was saved as {backup.name}."
            logger.error(msg)
            return ConfigLoadResult(AppConfig(), [msg], True, backup)

        config, warnings = AppConfig.from_dict(data)
        for w in warnings:
            logger.warning("Config: %s", w)
        return ConfigLoadResult(config, warnings)

    def save(self, config: AppConfig) -> None:
        """Atomically write the configuration (temp file + replace)."""
        config.normalize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        logger.debug("Configuration saved to %s", self.path)

    def _backup_corrupt_file(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, backup)
            return backup
        except OSError as exc:
            logger.error("Could not back up corrupt configuration: %s", exc)
            return None
