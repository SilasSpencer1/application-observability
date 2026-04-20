import sqlite3
from pathlib import Path
import pytest
from sync.db import Database

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
