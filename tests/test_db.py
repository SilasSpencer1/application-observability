import sqlite3
from pathlib import Path
import pytest
from sync.db import Database
from sync.classifier import Classification

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")

def test_schema_creates_expected_tables(db):
    db.init_schema()
    with sqlite3.connect(db.path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = [r[0] for r in rows]
    assert "applications" in names
    assert "status_events" in names

def test_schema_is_idempotent(db):
    db.init_schema()
    db.init_schema()  # second call should not raise


def _record(db, message_id, status, company="Stripe", role="SWE", occurred_at="2026-03-01T10:00:00Z"):
    return db.record_event(
        message_id=message_id,
        classification=Classification(status=status, company=company, role=role),
        occurred_at=occurred_at,
    )

def test_first_applied_event_creates_application(db):
    db.init_schema()
    _record(db, "m1", "applied", occurred_at="2026-03-01T10:00:00Z")
    with db.connect() as conn:
        apps = conn.execute("SELECT * FROM applications").fetchall()
        events = conn.execute("SELECT * FROM status_events").fetchall()
    assert len(apps) == 1
    assert apps[0]["current_status"] == "applied"
    assert len(events) == 1

def test_next_step_after_applied_updates_status(db):
    db.init_schema()
    _record(db, "m1", "applied", occurred_at="2026-03-01T10:00:00Z")
    _record(db, "m2", "next_step", occurred_at="2026-03-05T10:00:00Z")
    with db.connect() as conn:
        app = conn.execute("SELECT * FROM applications").fetchone()
        events = conn.execute("SELECT * FROM status_events ORDER BY occurred_at").fetchall()
    assert app["current_status"] == "next_step"
    assert app["status_updated_at"] == "2026-03-05T10:00:00Z"
    assert [e["status"] for e in events] == ["applied", "next_step"]

def test_duplicate_email_id_is_noop(db):
    db.init_schema()
    _record(db, "m1", "applied")
    _record(db, "m1", "applied")
    with db.connect() as conn:
        events = conn.execute("SELECT COUNT(*) AS c FROM status_events").fetchone()
    assert events["c"] == 1

def test_non_applied_event_with_no_existing_app_is_skipped(db):
    db.init_schema()
    result = _record(db, "m1", "rejected")
    assert result is None
    with db.connect() as conn:
        apps = conn.execute("SELECT COUNT(*) AS c FROM applications").fetchone()
    assert apps["c"] == 0
