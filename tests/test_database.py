import sqlite3

import pytest

from app.automation.models import Action, ActionType, ErrorPolicy, Profile
from app.automation.repository import ProfileError, ProfileRepository
from app.database.db import SCHEMA_VERSION, Database, DatabaseError
from app.monitoring.history import ActivityLogRepository, SessionHistoryRepository

TABLES = {"devices", "emulator_config", "location_presets", "gpx_files", "automation_profiles",
          "automation_actions", "session_history", "activity_logs", "app_settings"}


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "pokepilot.db")
    yield d
    d.close()


def test_schema_created(db):
    assert TABLES <= db.table_names()
    assert db.schema_version() == SCHEMA_VERSION
    assert db.query_one("PRAGMA foreign_keys")[0] == 1


def test_reopen_keeps_data(tmp_path):
    d = Database(tmp_path / "x.db")
    ProfileRepository(d).save(Profile("A", actions=[Action(ActionType.PRESS_BACK)]))
    d.close()
    d2 = Database(tmp_path / "x.db")
    assert [n for _, n, _ in ProfileRepository(d2).list()] == ["A"]
    d2.close()


def test_corrupt_database_backed_up(tmp_path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"this is not a database" * 100)
    d = Database(path)
    assert d.recovered_from is not None and d.recovered_from.exists()
    assert TABLES <= d.table_names()
    d.close()


def test_newer_schema_rejected(tmp_path):
    path = tmp_path / "new.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(DatabaseError):
        Database(path)


def test_transaction_rollback(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO app_settings VALUES ('k','v','t')")
            raise RuntimeError("boom")
    assert db.query("SELECT * FROM app_settings") == []


def test_check_constraints(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO location_presets (name, latitude, longitude, created_at, updated_at) "
                   "VALUES ('x', 95, 0, 't', 't')")


def test_profile_crud(db):
    repo = ProfileRepository(db)
    p = Profile("Daily", "d", [Action(ActionType.WAIT, {"seconds": 1.5}, 5),
                               Action(ActionType.TAP, {"element": "menu"}, expected_state="menu_open",
                                      error_policy=ErrorPolicy.RETRY, max_retries=2)])
    pid = repo.save(p)
    loaded = repo.get(pid)
    assert loaded.name == "Daily" and [a.to_dict() for a in loaded.actions] == [a.to_dict() for a in p.actions]
    loaded.actions.reverse()
    loaded.name = "Daily 2"
    repo.save(loaded)
    again = repo.get(pid)
    assert again.name == "Daily 2" and again.actions[0].type is ActionType.TAP
    with pytest.raises(ProfileError):
        repo.save(Profile("Daily 2", actions=[]))
    with pytest.raises(ProfileError):
        repo.save(Profile("  "))
    dup = repo.duplicate(pid)
    assert repo.get(dup).name == "Daily 2 copy"
    assert repo.get(repo.duplicate(pid)).name == "Daily 2 copy (2)"
    repo.delete(pid)
    with pytest.raises(ProfileError):
        repo.get(pid)
    assert db.query("SELECT COUNT(*) FROM automation_actions WHERE profile_id=?", (pid,))[0][0] == 0  # cascade


def test_profile_import_export(db):
    repo = ProfileRepository(db)
    pid = repo.save(Profile("Route", actions=[Action(ActionType.PRESS_BACK)]))
    text = repo.get(pid).to_json()
    new_id = repo.import_json(text)
    assert repo.get(new_id).name == "Route (2)"


def test_history_and_logs(db):
    hist = SessionHistoryRepository(db)
    sid = hist.start(None, "p", "emulator-5554", 3)
    logs = ActivityLogRepository(db, max_rows=5)
    for i in range(8):
        logs.add("INFO" if i % 2 else "ERROR", "automation", f"m{i}", sid)
    logs.prune()
    assert len(logs.recent(100)) == 5
    assert all(r["level"] == "ERROR" for r in logs.recent(100, "ERROR"))
    hist.finish(sid, "COMPLETED", 2, 0, 1, "")
    rec = hist.recent()[0]
    assert rec.result == "COMPLETED" and rec.unknown == 1 and rec.ended_at
    sid2 = hist.start(None, "p", "s", 1)
    assert hist.mark_interrupted() == 1
    assert hist.recent()[0].id == sid2 and hist.recent()[0].result == "INTERRUPTED"
