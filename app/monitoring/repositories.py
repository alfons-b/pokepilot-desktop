"""Device, emulator instance and key/value settings persistence; DB log handler."""

from __future__ import annotations

import logging
import threading

from app.database.db import Database, now_iso
from app.emulator.instances import EmulatorInstance
from app.emulator.models import AdbDevice, DeviceInfo
from app.monitoring.history import ActivityLogRepository


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_seen(self, devices: list[AdbDevice]) -> None:
        ts = now_iso()
        with self.db.transaction() as conn:
            for d in devices:
                conn.execute(
                    "INSERT INTO devices (serial, model, last_state, first_seen, last_seen) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(serial) DO UPDATE SET model=CASE WHEN excluded.model != '' THEN excluded.model "
                    "ELSE devices.model END, last_state=excluded.last_state, last_seen=excluded.last_seen",
                    (d.serial, d.model, d.raw_state or d.state.value, ts, ts),
                )

    def update_info(self, info: DeviceInfo) -> None:
        res = info.format_resolution(info.effective_resolution) if info.effective_resolution else ""
        self.db.execute(
            "UPDATE devices SET android_version=?, resolution=?, model=CASE WHEN ? != '' THEN ? ELSE model END "
            "WHERE serial=?",
            (info.android_version, res, info.model, info.model, info.serial),
        )

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM devices ORDER BY last_seen DESC")]


class EmulatorConfigRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, instances: list[EmulatorInstance]) -> None:
        ts = now_iso()
        with self.db.transaction() as conn:
            for i in instances:
                conn.execute(
                    "INSERT INTO emulator_config (provider, instance_name, display_name, adb_address, "
                    "launch_executable, launch_args, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(provider, instance_name) DO UPDATE SET display_name=excluded.display_name, "
                    "adb_address=excluded.adb_address, launch_executable=excluded.launch_executable, "
                    "launch_args=excluded.launch_args, updated_at=excluded.updated_at",
                    (i.provider, i.name, i.display_name, i.adb_address, i.launch_executable,
                     " ".join(i.launch_args), ts, ts),
                )

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM emulator_config ORDER BY provider, instance_name")]


class SettingsRepository:
    """Small key/value store for application metadata (user settings live in config.json)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM app_settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now_iso()),
        )


class DatabaseLogHandler(logging.Handler):
    """Persist WARNING+ log records to activity_logs. Never raises into the caller."""

    def __init__(self, logs: ActivityLogRepository, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self._logs = logs
        self._local = threading.local()
        self.session_id_provider = lambda: None

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._local, "busy", False) or record.name.startswith("app.database"):
            return  # avoid recursion if writing the log itself logs
        if record.name == "app.automation.engine":
            return  # session messages are already stored by the session manager
        self._local.busy = True
        try:
            self._logs.add(record.levelname, record.name, self.format(record), self.session_id_provider())
        except Exception:  # noqa: BLE001 - logging must not crash the app
            pass
        finally:
            self._local.busy = False
