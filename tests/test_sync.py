from pathlib import Path
from types import SimpleNamespace
import pytest
from sync.db import Database
from sync.classifier import Classifier
from sync.sync import run_sync, build_client, RULES_PATH


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


def test_build_client_rejects_unknown_provider():
    with pytest.raises(RuntimeError, match="Unknown AAO_PROVIDER"):
        build_client("outlook")


def test_build_client_gmail_requires_credentials_path(monkeypatch):
    monkeypatch.delenv("AAO_GOOGLE_CREDENTIALS", raising=False)
    with pytest.raises(RuntimeError, match="AAO_GOOGLE_CREDENTIALS"):
        build_client("gmail")


def test_build_client_graph_requires_client_id(monkeypatch):
    monkeypatch.delenv("AAO_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="AAO_CLIENT_ID"):
        build_client("graph")


def test_build_client_gmail_returns_gmail_client(tmp_path, monkeypatch):
    fake_creds = tmp_path / "google_credentials.json"
    fake_creds.write_text('{"installed": {"client_id": "x"}}')
    monkeypatch.setenv("AAO_GOOGLE_CREDENTIALS", str(fake_creds))
    from sync.gmail_client import GmailClient

    client = build_client("gmail")
    assert isinstance(client, GmailClient)
    assert client.credentials_path == fake_creds


def test_build_client_graph_returns_graph_client(monkeypatch):
    monkeypatch.setenv("AAO_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("AAO_TENANT", "common")
    from sync.graph_client import GraphClient

    client = build_client("graph")
    assert isinstance(client, GraphClient)
    assert client.client_id == "fake-client-id"
