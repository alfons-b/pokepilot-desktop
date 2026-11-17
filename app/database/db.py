"""SQLite database: connection management, schema and migrations.

A single connection is shared and guarded by a re-entrant lock so repositories
can be used from worker threads. Foreign keys are enforced; writes use explicit
transactions via :meth:`Database.transaction`.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.core.fileutil import backup_corrupt

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    serial          TEXT NOT NULL UNIQUE,
    model           TEXT NOT NULL DEFAULT '',
    android_version TEXT NOT NULL DEFAULT '',
    resolution      TEXT NOT NULL DEFAULT '',
    last_state      TEXT NOT NULL DEFAULT '',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emulator_config (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,
    instance_name     TEXT NOT NULL,
    display_name      TEXT NOT NULL DEFAULT '',
    adb_address       TEXT,
    launch_executable TEXT,
    launch_args       TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (provider, instance_name)
);

CREATE TABLE IF NOT EXISTS location_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    latitude    REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude   REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    notes       TEXT NOT NULL DEFAULT '',
    favorite    INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_locations_name ON location_presets (name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_locations_favorite ON location_presets (favorite);

CREATE TABLE IF NOT EXISTS gpx_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    file_path    TEXT NOT NULL UNIQUE,
    point_count  INTEGER NOT NULL DEFAULT 0,
    track_count  INTEGER NOT NULL DEFAULT 0,
    distance_m   REAL NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gpx_name ON gpx_files (name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS automation_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_actions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id     INTEGER NOT NULL REFERENCES automation_profiles (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    action_uid     TEXT NOT NULL,
    action_type    TEXT NOT NULL,
    params_json    TEXT NOT NULL DEFAULT '{}',
    timeout_s      REAL NOT NULL,
    expected_state TEXT,
    error_policy   TEXT NOT NULL,
    max_retries    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (profile_id, position)
);
CREATE INDEX IF NOT EXISTS idx_actions_profile ON automation_actions (profile_id);

CREATE TABLE IF NOT EXISTS session_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id        INTEGER REFERENCES automation_profiles (id) ON DELETE SET NULL,
    profile_name      TEXT NOT NULL,
    device_serial     TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    result            TEXT NOT NULL DEFAULT 'RUNNING',
    actions_total     INTEGER NOT NULL DEFAULT 0,
    actions_succeeded INTEGER NOT NULL DEFAULT 0,
    actions_failed    INTEGER NOT NULL DEFAULT 0,
    actions_unknown   INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON session_history (started_at);

CREATE TABLE IF NOT EXISTS activity_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    level      TEXT NOT NULL,
    source     TEXT NOT NULL,
    message    TEXT NOT NULL,
    session_id INTEGER REFERENCES session_history (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON activity_logs (timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_session ON activity_logs (session_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MIGRATIONS: dict[int, str] = {1: SCHEMA_V1}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DatabaseError(Exception):
    pass


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        self.recovered_from: Path | None = None
        self._lock = threading.RLock()
        self._conn = self._open(str(path))

    def _open(self, target: str) -> sqlite3.Connection:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._connect(target)
            conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            if self.path is None or not self.path.exists():
                raise DatabaseError(str(exc)) from exc
            logger.error("Database %s is corrupt (%s); backing it up and starting fresh.", self.path, exc)
            self.recovered_from = backup_corrupt(self.path)
            conn = self._connect(target)
        self._migrate(conn)
        return conn

    @staticmethod
    def _connect(target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise DatabaseError(f"Database schema v{current} is newer than this application (v{SCHEMA_VERSION}).")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            logger.info("Applying database migration v%d", version)
            conn.execute("BEGIN")
            try:
                for stmt in filter(str.strip, MIGRATIONS[version].split(";")):
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ API
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run statements atomically: commits on success, rolls back on any exception."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """Execute a single write in its own transaction; returns lastrowid."""
        with self.transaction() as conn:
            return conn.execute(sql, params).lastrowid or 0

    def schema_version(self) -> int:
        return self.query_one("PRAGMA user_version")[0]

    def table_names(self) -> set[str]:
        return {r[0] for r in self.query("SELECT name FROM sqlite_master WHERE type='table'")}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
