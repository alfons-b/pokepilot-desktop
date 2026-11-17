"""Session history and activity log persistence."""

from __future__ import annotations

from dataclasses import dataclass

from app.database.db import Database, now_iso

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass(frozen=True)
class SessionRecord:
    id: int
    profile_name: str
    device_serial: str
    started_at: str
    ended_at: str | None
    result: str
    total: int
    succeeded: int
    failed: int
    unknown: int
    last_error: str


class SessionHistoryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, profile_id: int | None, profile_name: str, serial: str, total: int) -> int:
        return self.db.execute(
            "INSERT INTO session_history (profile_id, profile_name, device_serial, started_at, result, actions_total)"
            " VALUES (?,?,?,?, 'RUNNING', ?)",
            (profile_id, profile_name, serial, now_iso(), total),
        )

    def finish(self, session_id: int, result: str, succeeded: int, failed: int, unknown: int, last_error: str) -> None:
        self.db.execute(
            "UPDATE session_history SET ended_at=?, result=?, actions_succeeded=?, actions_failed=?, "
            "actions_unknown=?, last_error=? WHERE id=?",
            (now_iso(), result, succeeded, failed, unknown, last_error, session_id),
        )

    def mark_interrupted(self) -> int:
        """Sessions left RUNNING by a crash/kill are closed as INTERRUPTED at startup."""
        with self.db.transaction() as conn:
            return conn.execute(
                "UPDATE session_history SET result='INTERRUPTED', ended_at=? WHERE result='RUNNING'", (now_iso(),)
            ).rowcount

    def recent(self, limit: int = 100) -> list[SessionRecord]:
        rows = self.db.query("SELECT * FROM session_history ORDER BY id DESC LIMIT ?", (limit,))
        return [
            SessionRecord(r["id"], r["profile_name"], r["device_serial"], r["started_at"], r["ended_at"], r["result"],
                          r["actions_total"], r["actions_succeeded"], r["actions_failed"], r["actions_unknown"],
                          r["last_error"])
            for r in rows
        ]


class ActivityLogRepository:
    def __init__(self, db: Database, max_rows: int = 50_000) -> None:
        self.db = db
        self.max_rows = max_rows
        self._inserts = 0

    def add(self, level: str, source: str, message: str, session_id: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO activity_logs (timestamp, level, source, message, session_id) VALUES (?,?,?,?,?)",
            (now_iso(), level, source[:100], message[:4000], session_id),
        )
        self._inserts += 1
        if self._inserts % 500 == 0:
            self.prune()

    def prune(self) -> None:
        self.db.execute(
            "DELETE FROM activity_logs WHERE id <= (SELECT MAX(id) FROM activity_logs) - ?", (self.max_rows,)
        )

    def recent(self, limit: int = 200, min_level: str = "DEBUG", session_id: int | None = None) -> list[dict]:
        allowed = LEVELS[LEVELS.index(min_level):] if min_level in LEVELS else LEVELS
        sql = f"SELECT * FROM activity_logs WHERE level IN ({','.join('?' * len(allowed))})"
        params: list = list(allowed)
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.query(sql, tuple(params))]
