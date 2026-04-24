import textwrap
from pathlib import Path

import pytest

from sync.classifier import Classifier
from sync.db import Database
from sync.eml_import import (
    _normalize_date_header,
    _resolve_paths,
    import_files,
    parse_eml,
)
from sync.sync import RULES_PATH


def _write_eml(path: Path, subject: str, sender: str, date: str, body: str) -> Path:
    path.write_text(
        textwrap.dedent(
            f"""\
            From: {sender}
            To: me@example.com
            Subject: {subject}
            Date: {date}
            Message-ID: <{path.stem}@example.com>
            Content-Type: text/plain; charset="utf-8"

            {body}
            """
        )
    )
    return path


@pytest.fixture
def classifier():
    return Classifier.from_yaml(RULES_PATH)


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "jobs.db")
    db.init_schema()
    return db


def test_parse_eml_reads_headers_and_body(tmp_path):
    path = _write_eml(
        tmp_path / "applied.eml",
        subject="Thank you for applying to Acme",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 01 Mar 2026 10:00:00 +0000",
        body="Thanks for taking the time to apply for the Backend Engineer role at Acme.",
    )
    email_obj = parse_eml(path)
    assert email_obj.subject == "Thank you for applying to Acme"
    assert email_obj.from_name == "Acme Recruiting"
    assert email_obj.from_address == "no-reply@example.com"
    assert email_obj.received_at == "2026-03-01T10:00:00Z"
    assert "Backend Engineer" in email_obj.body


def test_parse_eml_without_date_falls_back_to_now(tmp_path):
    path = tmp_path / "no-date.eml"
    path.write_text(
        "From: x@example.com\nSubject: whatever\nContent-Type: text/plain\n\nHi\n"
    )
    email_obj = parse_eml(path)
    # The fallback uses datetime.now(); just assert the format is canonical.
    assert email_obj.received_at.endswith("Z")
    assert len(email_obj.received_at) == len("YYYY-MM-DDTHH:MM:SSZ")


def test_resolve_paths_expands_directory(tmp_path):
    (tmp_path / "a.eml").write_text("From: x\nSubject: y\n\nz")
    (tmp_path / "b.eml").write_text("From: x\nSubject: y\n\nz")
    (tmp_path / "ignore.txt").write_text("not an eml")
    found = _resolve_paths([tmp_path])
    assert [p.name for p in found] == ["a.eml", "b.eml"]


def test_import_files_records_applied(classifier, db, tmp_path):
    path = _write_eml(
        tmp_path / "acme.eml",
        subject="Thank you for applying to Acme",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 01 Mar 2026 10:00:00 +0000",
        body="Thanks for taking the time to apply for the Backend Engineer role at Acme.",
    )
    counts = import_files([path], classifier, db)
    assert counts.recorded == 1
    assert counts.unknown_baseline == 0
    with db.connect() as conn:
        apps = conn.execute("SELECT company, role, current_status, applied_at FROM applications").fetchall()
    assert len(apps) == 1
    assert apps[0]["company"] == "Acme"
    assert apps[0]["current_status"] == "applied"
    assert apps[0]["applied_at"] == "2026-03-01T10:00:00Z"


def test_import_files_creates_baseline_for_rejection_only(classifier, db, tmp_path):
    path = _write_eml(
        tmp_path / "nope.eml",
        subject="Update on your application",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 15 Mar 2026 10:00:00 +0000",
        body=(
            "Thanks for your interest in the Backend Engineer role. "
            "Unfortunately we have decided to move forward with other candidates."
        ),
    )
    counts = import_files([path], classifier, db)
    assert counts.recorded == 1
    assert counts.unknown_baseline == 1
    with db.connect() as conn:
        app = conn.execute(
            "SELECT company, current_status, applied_at, status_updated_at FROM applications"
        ).fetchone()
    assert app["current_status"] == "rejected"
    assert app["applied_at"] is None
    assert app["status_updated_at"] == "2026-03-15T10:00:00Z"


def test_import_files_skips_non_job_emails(classifier, db, tmp_path):
    path = _write_eml(
        tmp_path / "noise.eml",
        subject="Weekly newsletter",
        sender="Random News <news@example.com>",
        date="Mon, 01 Mar 2026 10:00:00 +0000",
        body="This week's top stories in product launches and industry trends.",
    )
    counts = import_files([path], classifier, db)
    assert counts.recorded == 0
    assert counts.skipped == 1


def test_import_is_idempotent(classifier, db, tmp_path):
    path = _write_eml(
        tmp_path / "acme.eml",
        subject="Thank you for applying to Acme",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 01 Mar 2026 10:00:00 +0000",
        body="Thank you for applying to the Backend Engineer role at Acme.",
    )
    import_files([path], classifier, db)
    counts = import_files([path], classifier, db)
    assert counts.recorded == 0
    assert counts.duplicates == 1


def test_applied_after_rejection_backfills_applied_at(classifier, db, tmp_path):
    reject = _write_eml(
        tmp_path / "reject.eml",
        subject="Update on your application",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 15 Mar 2026 10:00:00 +0000",
        body="Thanks for your interest in the Backend Engineer role. Unfortunately we cannot proceed.",
    )
    applied = _write_eml(
        tmp_path / "applied.eml",
        subject="Thank you for applying to Acme",
        sender="Acme Recruiting <no-reply@example.com>",
        date="Mon, 01 Mar 2026 10:00:00 +0000",
        body="Thank you for applying to the Backend Engineer role at Acme.",
    )
    import_files([reject, applied], classifier, db)
    with db.connect() as conn:
        app = conn.execute(
            "SELECT current_status, applied_at FROM applications"
        ).fetchone()
    # Later rejection still wins on current_status because it is newer.
    assert app["current_status"] == "rejected"
    # But the real applied_at should have been backfilled.
    assert app["applied_at"] == "2026-03-01T10:00:00Z"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Mon, 01 Mar 2026 10:00:00 +0000", "2026-03-01T10:00:00Z"),
        ("Mon, 01 Mar 2026 05:00:00 -0500", "2026-03-01T10:00:00Z"),
    ],
)
def test_normalize_date_header(raw, expected):
    assert _normalize_date_header(raw) == expected
