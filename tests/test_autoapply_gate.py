from datetime import datetime, timedelta, timezone
import pytest

from sync.autoapply.gate import AutoApplyGate, REJECTED_COOLDOWN_DAYS
from sync.db import Database
from sync.classifier import Classification


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return db


def _record(db, message_id, status, *, company="Stripe", role="SWE",
            occurred_at="2026-03-01T10:00:00Z"):
    db.record_event(
        message_id=message_id,
        classification=Classification(status=status, company=company, role=role),
        occurred_at=occurred_at,
    )


def test_empty_db_lets_everything_through(db):
    g = AutoApplyGate(db)
    assert g.should_apply("Stripe", "SWE") is True
    assert g.should_apply("Acme", None) is True


def test_applied_blocks(db):
    _record(db, "m1", "applied")
    assert AutoApplyGate(db).should_apply("Stripe", "SWE") is False


def test_next_step_blocks(db):
    _record(db, "m1", "applied")
    _record(db, "m2", "next_step", occurred_at="2026-03-05T10:00:00Z")
    assert AutoApplyGate(db).should_apply("Stripe", "SWE") is False


def test_offer_blocks(db):
    _record(db, "m1", "applied")
    _record(db, "m2", "offer", occurred_at="2026-03-05T10:00:00Z")
    assert AutoApplyGate(db).should_apply("Stripe", "SWE") is False


def test_rejected_within_cooldown_blocks(db):
    _record(db, "m1", "applied", occurred_at="2026-01-01T10:00:00Z")
    _record(db, "m2", "rejected", occurred_at="2026-01-10T10:00:00Z")
    now = datetime(2026, 2, 9, tzinfo=timezone.utc)  # 30 days later
    assert AutoApplyGate(db, now=now).should_apply("Stripe", "SWE") is False


def test_rejected_just_past_cooldown_allows(db):
    _record(db, "m1", "applied", occurred_at="2026-01-01T10:00:00Z")
    _record(db, "m2", "rejected", occurred_at="2026-01-10T10:00:00Z")
    rejected_at = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    now = rejected_at + timedelta(days=REJECTED_COOLDOWN_DAYS, seconds=1)
    assert AutoApplyGate(db, now=now).should_apply("Stripe", "SWE") is True


def test_rejected_exactly_at_cooldown_boundary_allows(db):
    _record(db, "m1", "applied", occurred_at="2026-01-01T10:00:00Z")
    _record(db, "m2", "rejected", occurred_at="2026-01-10T10:00:00Z")
    rejected_at = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    now = rejected_at + timedelta(days=REJECTED_COOLDOWN_DAYS)
    assert AutoApplyGate(db, now=now).should_apply("Stripe", "SWE") is True


def test_different_role_at_same_company_allows(db):
    _record(db, "m1", "applied", role="SWE")
    assert AutoApplyGate(db).should_apply("Stripe", "Data Scientist") is True


def test_different_company_same_role_allows(db):
    _record(db, "m1", "applied", company="Stripe", role="SWE")
    assert AutoApplyGate(db).should_apply("Acme", "SWE") is True


def test_null_role_matches_only_null_role(db):
    _record(db, "m1", "applied", role=None)
    assert AutoApplyGate(db).should_apply("Stripe", None) is False
    assert AutoApplyGate(db).should_apply("Stripe", "SWE") is True


def test_naive_iso_timestamp_in_db_is_treated_as_utc(db):
    # Defensive case: if something writes a naive (tz-less) ISO string to the
    # DB, the gate should still compare against an aware 'now' without
    # TypeError, by coercing the parsed datetime to UTC.
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO applications "
            "(company, role, first_email_id, applied_at, current_status, status_updated_at) "
            "VALUES ('Stripe', 'SWE', 'seed', '2026-01-01T00:00:00', 'rejected', '2026-01-10T00:00:00')"
        )
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)  # within cooldown
    assert AutoApplyGate(db, now=now).should_apply("Stripe", "SWE") is False


def test_rejection_then_later_applied_event_uses_latest_status(db):
    # An older rejection followed by a newer applied event means the
    # applications row is 'applied', so the rejected cooldown is irrelevant.
    _record(db, "m1", "applied", occurred_at="2025-06-01T10:00:00Z")
    _record(db, "m2", "rejected", occurred_at="2025-07-01T10:00:00Z")
    _record(db, "m3", "applied", occurred_at="2026-03-01T10:00:00Z")
    # Current status is 'applied', so gate blocks regardless of cooldown.
    assert AutoApplyGate(db).should_apply("Stripe", "SWE") is False
