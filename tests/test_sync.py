from pathlib import Path
from types import SimpleNamespace
import pytest
from sync.db import Database
from sync.classifier import Classifier
from sync.sync import run_sync, RULES_PATH


class FakeClient:
    def __init__(self, messages):
        self._messages = messages

    def fetch_messages_since(self, since_iso):
        yield from self._messages


def _msg(**kw):
    defaults = dict(
        message_id="msg-x",
        subject="Thank you for applying to Stripe",
        from_name="Stripe Recruiting",
        from_address="no-reply@us.greenhouse-mail.io",
        body="Hi Silas, thank you for applying to the Software Engineer role at Stripe.",
        received_at="2026-03-01T10:00:00Z",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.fixture
def classifier():
    return Classifier.from_yaml(RULES_PATH)


def test_run_sync_classifies_and_records_applied(tmp_path, classifier):
    db = Database(tmp_path / "jobs.db")
    db.init_schema()
    client = FakeClient([_msg(message_id="m1")])
    counts = run_sync(client, classifier, db, since_iso=None)
    assert counts["seen"] == 1
    assert counts["classified"] == 1
    assert counts["recorded"] == 1
    assert counts["skipped"] == 0
    with db.connect() as conn:
        apps = conn.execute("SELECT * FROM applications").fetchall()
    assert len(apps) == 1


def test_run_sync_skips_unclassifiable_emails(tmp_path, classifier):
    db = Database(tmp_path / "jobs.db")
    db.init_schema()
    noise = _msg(
        message_id="m-noise",
        subject="Weekly newsletter",
        body="Nothing related to jobs here.",
    )
    client = FakeClient([noise])
    counts = run_sync(client, classifier, db, since_iso=None)
    assert counts["seen"] == 1
    assert counts["skipped"] == 1
    assert counts["recorded"] == 0


def test_run_sync_counts_duplicates(tmp_path, classifier):
    db = Database(tmp_path / "jobs.db")
    db.init_schema()
    m = _msg(message_id="m-dup")
    # First call records it, second call hits the db dedup
    run_sync(FakeClient([m]), classifier, db, since_iso=None)
    counts = run_sync(FakeClient([m]), classifier, db, since_iso=None)
    assert counts["duplicates"] == 1
    assert counts["recorded"] == 0
