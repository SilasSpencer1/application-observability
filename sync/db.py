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
    location TEXT,
    first_email_id TEXT NOT NULL,
    applied_at DATETIME,
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
            self._migrate(conn)

    def _migrate(self, conn) -> None:
        cols = list(conn.execute("PRAGMA table_info(applications)"))
        by_name = {row["name"]: row for row in cols}
        if "location" not in by_name:
            conn.execute("ALTER TABLE applications ADD COLUMN location TEXT")
        # SQLite cannot relax a NOT NULL column in place; rebuild when needed.
        if by_name.get("applied_at") and by_name["applied_at"]["notnull"] == 1:
            # Foreign keys must be off during the rebuild so dropping the old
            # applications table does not trip the status_events FK.
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.executescript(
                    """
                    CREATE TABLE applications_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company TEXT NOT NULL,
                        role TEXT,
                        location TEXT,
                        first_email_id TEXT NOT NULL,
                        applied_at DATETIME,
                        current_status TEXT NOT NULL CHECK (current_status IN ('applied','next_step','rejected','offer')),
                        status_updated_at DATETIME NOT NULL
                    );
                    INSERT INTO applications_new
                        (id, company, role, location, first_email_id, applied_at, current_status, status_updated_at)
                        SELECT id, company, role, location, first_email_id, applied_at, current_status, status_updated_at
                        FROM applications;
                    DROP TABLE applications;
                    ALTER TABLE applications_new RENAME TO applications;
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_company_role
                        ON applications(company, COALESCE(role, ''));
                    """
                )
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

    def record_event(
        self,
        message_id: str,
        classification: Classification,
        occurred_at: str,
        allow_unknown_applied_at: bool = False,
    ) -> int | None:
        """Insert a status event and update or create the parent application.

        Returns the application_id touched, or None if the event was skipped.
        Idempotent: a duplicate message_id is a no-op.

        When `allow_unknown_applied_at` is True, a decision event (rejected,
        next step, offer) for a company+role we have never seen still creates
        an application row with a null `applied_at`. This is the path the
        manual CLI and the eml importer use, since the user can be sure the
        application happened even if we don't have the confirmation email.
        """
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM status_events WHERE email_id = ?", (message_id,)
            ).fetchone()
            if existing:
                return None

            company_norm = classification.company or "Unknown"
            role_norm = classification.role
            location_norm = classification.location

            app_row = conn.execute(
                "SELECT id, current_status, status_updated_at, applied_at FROM applications "
                "WHERE company = ? AND COALESCE(role, '') = COALESCE(?, '')",
                (company_norm, role_norm),
            ).fetchone()

            if app_row is None:
                is_applied = classification.status == "applied"
                if not is_applied and not allow_unknown_applied_at:
                    return None
                new_applied_at = occurred_at if is_applied else None
                cur = conn.execute(
                    "INSERT INTO applications "
                    "(company, role, location, first_email_id, applied_at, current_status, status_updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        company_norm,
                        role_norm,
                        location_norm,
                        message_id,
                        new_applied_at,
                        classification.status,
                        occurred_at,
                    ),
                )
                app_id = cur.lastrowid
            else:
                app_id = app_row["id"]
                if occurred_at >= app_row["status_updated_at"]:
                    conn.execute(
                        "UPDATE applications SET current_status = ?, status_updated_at = ? WHERE id = ?",
                        (classification.status, occurred_at, app_id),
                    )
                if classification.status == "applied" and app_row["applied_at"] is None:
                    conn.execute(
                        "UPDATE applications SET applied_at = ?, first_email_id = ? WHERE id = ?",
                        (occurred_at, message_id, app_id),
                    )
                if location_norm:
                    conn.execute(
                        "UPDATE applications SET location = COALESCE(location, ?) WHERE id = ?",
                        (location_norm, app_id),
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
