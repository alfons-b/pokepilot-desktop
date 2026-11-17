"""Persistence of automation profiles in SQLite."""

from __future__ import annotations

import json
import sqlite3

from app.automation.models import Action, ActionType, ErrorPolicy, Profile
from app.database.db import Database, now_iso


class ProfileError(Exception):
    pass


class ProfileRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[tuple[int, str, int]]:
        """Return (id, name, action count) sorted by name."""
        rows = self.db.query(
            "SELECT p.id, p.name, COUNT(a.id) AS n FROM automation_profiles p "
            "LEFT JOIN automation_actions a ON a.profile_id = p.id GROUP BY p.id ORDER BY p.name COLLATE NOCASE"
        )
        return [(r["id"], r["name"], r["n"]) for r in rows]

    def get(self, profile_id: int) -> Profile:
        row = self.db.query_one("SELECT * FROM automation_profiles WHERE id = ?", (profile_id,))
        if row is None:
            raise ProfileError(f"Profile {profile_id} does not exist.")
        actions = [
            Action(
                type=ActionType(r["action_type"]),
                params=json.loads(r["params_json"]),
                timeout_s=r["timeout_s"],
                expected_state=r["expected_state"],
                error_policy=ErrorPolicy(r["error_policy"]),
                max_retries=r["max_retries"],
                uid=r["action_uid"],
            )
            for r in self.db.query(
                "SELECT * FROM automation_actions WHERE profile_id = ? ORDER BY position", (profile_id,)
            )
        ]
        return Profile(row["name"], row["description"], actions, row["id"])

    def save(self, profile: Profile) -> int:
        """Insert or update a profile and replace its actions atomically."""
        name = profile.name.strip()
        if not name:
            raise ProfileError("Profile name is required.")
        ts = now_iso()
        try:
            with self.db.transaction() as conn:
                if profile.id is None:
                    cur = conn.execute(
                        "INSERT INTO automation_profiles (name, description, created_at, updated_at) VALUES (?,?,?,?)",
                        (name, profile.description, ts, ts),
                    )
                    profile.id = cur.lastrowid
                else:
                    cur = conn.execute(
                        "UPDATE automation_profiles SET name=?, description=?, updated_at=? WHERE id=?",
                        (name, profile.description, ts, profile.id),
                    )
                    if cur.rowcount == 0:
                        raise ProfileError(f"Profile {profile.id} does not exist.")
                    conn.execute("DELETE FROM automation_actions WHERE profile_id = ?", (profile.id,))
                conn.executemany(
                    "INSERT INTO automation_actions (profile_id, position, action_uid, action_type, params_json, "
                    "timeout_s, expected_state, error_policy, max_retries) VALUES (?,?,?,?,?,?,?,?,?)",
                    [
                        (profile.id, i, a.uid, a.type.value, json.dumps(a.params), a.timeout_s, a.expected_state,
                         a.error_policy.value, a.max_retries)
                        for i, a in enumerate(profile.actions)
                    ],
                )
        except sqlite3.IntegrityError as exc:
            if "automation_profiles.name" in str(exc):
                raise ProfileError(f"A profile named '{name}' already exists.") from exc
            raise ProfileError(str(exc)) from exc
        profile.name = name
        return profile.id  # type: ignore[return-value]

    def delete(self, profile_id: int) -> None:
        self.db.execute("DELETE FROM automation_profiles WHERE id = ?", (profile_id,))

    def unique_name(self, base: str) -> str:
        names = {n.lower() for _, n, _ in self.list()}
        if base.lower() not in names:
            return base
        i = 2
        while f"{base} ({i})".lower() in names:
            i += 1
        return f"{base} ({i})"

    def duplicate(self, profile_id: int) -> int:
        src = self.get(profile_id)
        copy = Profile.from_json(src.to_json())  # deep copy with fresh action ids
        copy.name = self.unique_name(f"{src.name} copy")
        return self.save(copy)

    def import_json(self, text: str) -> int:
        profile = Profile.from_json(text)
        profile.name = self.unique_name(profile.name)
        return self.save(profile)
