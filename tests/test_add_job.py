import pytest

from sync.add_job import _normalize_date, main
from sync.db import Database


def test_normalize_date_accepts_date_only():
    assert _normalize_date("2026-03-15") == "2026-03-15T00:00:00Z"


def test_normalize_date_accepts_iso():
    assert _normalize_date("2026-03-15T12:34:56Z") == "2026-03-15T12:34:56Z"


def test_normalize_date_returns_none_for_none():
    assert _normalize_date(None) is None


def test_normalize_date_rejects_garbage():
    with pytest.raises(SystemExit):
        _normalize_date("not a date")


def test_main_adds_applied_row(tmp_path):
    db_path = tmp_path / "jobs.db"
    code = main(
        [
            "--company",
            "Acme",
            "--role",
            "Backend Engineer",
            "--applied-at",
            "2026-03-01",
            "--db-path",
            str(db_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert code == 0
    db = Database(db_path)
    with db.connect() as conn:
        row = conn.execute("SELECT company, role, current_status, applied_at FROM applications").fetchone()
    assert row["company"] == "Acme"
    assert row["role"] == "Backend Engineer"
    assert row["current_status"] == "applied"
    assert row["applied_at"] == "2026-03-01T00:00:00Z"


def test_main_records_rejection_with_unknown_applied_at(tmp_path):
    db_path = tmp_path / "jobs.db"
    code = main(
        [
            "--company",
            "Acme",
            "--role",
            "Backend Engineer",
            "--status",
            "rejected",
            "--occurred-at",
            "2026-03-15",
            "--db-path",
            str(db_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert code == 0
    db = Database(db_path)
    with db.connect() as conn:
        row = conn.execute("SELECT current_status, applied_at FROM applications").fetchone()
    assert row["current_status"] == "rejected"
    assert row["applied_at"] is None


def test_main_seeds_applied_when_status_is_decision_with_applied_date(tmp_path):
    db_path = tmp_path / "jobs.db"
    code = main(
        [
            "--company",
            "Acme",
            "--role",
            "Backend Engineer",
            "--status",
            "next_step",
            "--applied-at",
            "2026-03-01",
            "--occurred-at",
            "2026-03-08",
            "--db-path",
            str(db_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    assert code == 0
    db = Database(db_path)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT current_status, applied_at, status_updated_at FROM applications"
        ).fetchone()
        events = conn.execute(
            "SELECT status, occurred_at FROM status_events ORDER BY occurred_at"
        ).fetchall()
    assert row["current_status"] == "next_step"
    assert row["applied_at"] == "2026-03-01T00:00:00Z"
    assert row["status_updated_at"] == "2026-03-08T00:00:00Z"
    assert [(e["status"], e["occurred_at"]) for e in events] == [
        ("applied", "2026-03-01T00:00:00Z"),
        ("next_step", "2026-03-08T00:00:00Z"),
    ]


def test_main_duplicate_returns_exit_1(tmp_path):
    db_path = tmp_path / "jobs.db"
    args = [
        "--company",
        "Acme",
        "--role",
        "Backend Engineer",
        "--status",
        "applied",
        "--applied-at",
        "2026-03-01",
        "--db-path",
        str(db_path),
        "--log-dir",
        str(tmp_path / "logs"),
    ]
    assert main(args) == 0
    assert main(args) == 1
