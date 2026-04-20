from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sync.classifier import Classification

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

    def record_event(
        self,
        message_id: str,
        classification: Classification,
        occurred_at: str,
    ) -> int | None:
        """Insert a status event and update or create the parent application.

        Returns the application_id touched, or None if the event was skipped.
        Idempotent: a duplicate message_id is a no-op.
        """
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM status_events WHERE email_id = ?", (message_id,)
            ).fetchone()
            if existing:
                return None

            company_norm = classification.company or "Unknown"
            role_norm = classification.role

            app_row = conn.execute(
                "SELECT id, current_status, status_updated_at FROM applications "
                "WHERE company = ? AND COALESCE(role, '') = COALESCE(?, '')",
                (company_norm, role_norm),
            ).fetchone()

            if app_row is None:
                if classification.status != "applied":
                    return None
                cur = conn.execute(
                    "INSERT INTO applications "
                    "(company, role, first_email_id, applied_at, current_status, status_updated_at) "
                    "VALUES (?, ?, ?, ?, 'applied', ?)",
                    (company_norm, role_norm, message_id, occurred_at, occurred_at),
                )
                app_id = cur.lastrowid
            else:
                app_id = app_row["id"]
                if occurred_at >= app_row["status_updated_at"]:
                    conn.execute(
                        "UPDATE applications SET current_status = ?, status_updated_at = ? WHERE id = ?",
                        (classification.status, occurred_at, app_id),
                    )

            conn.execute(
                "INSERT INTO status_events (application_id, status, email_id, occurred_at) "
                "VALUES (?, ?, ?, ?)",
                (app_id, classification.status, message_id, occurred_at),
            )
            return app_id

    def last_event_at(self) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(occurred_at) AS m FROM status_events"
            ).fetchone()
        return row["m"]
