from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT,
    first_email_id TEXT NOT NULL,
    applied_at DATETIME NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN ('applied','next_step','rejected','offer')),
    status_updated_at DATETIME NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_company_role
    ON applications(company, COALESCE(role, ''));

CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    status TEXT NOT NULL CHECK (status IN ('applied','next_step','rejected','offer')),
    email_id TEXT NOT NULL UNIQUE,
    occurred_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_status_events_app
    ON status_events(application_id, occurred_at);
"""

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
