from __future__ import annotations
import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from sync.classifier import Classifier, Email
from sync.db import Database

DEFAULT_HOME = Path.home() / ".application-observability"
DEFAULT_DB_PATH = DEFAULT_HOME / "jobs.db"
DEFAULT_LOG_DIR = DEFAULT_HOME / "logs"
RULES_PATH = Path(__file__).parent / "rules.yaml"
DEFAULT_PROVIDER = "gmail"

log = logging.getLogger("sync")


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        log_dir / "sync.log", when="W0", backupCount=8, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)


def _to_email(msg) -> Email:
    """Convert a provider-specific message dataclass into our canonical Email."""
    return Email(
        message_id=msg.message_id,
        subject=msg.subject,
        from_name=msg.from_name,
        from_address=msg.from_address,
        body=msg.body,
        received_at=msg.received_at,
    )


def build_client(provider: str):
    """Construct the configured mail provider client from environment variables."""
    provider = provider.lower()
    if provider == "gmail":
        from sync.gmail_client import GmailClient

        credentials_path = os.environ.get("AAO_GOOGLE_CREDENTIALS")
        if not credentials_path:
            raise RuntimeError(
                "AAO_GOOGLE_CREDENTIALS must point to a Google OAuth client JSON file"
            )
        return GmailClient(credentials_path=Path(credentials_path))
    if provider == "graph":
        from sync.graph_client import GraphClient

        client_id = os.environ.get("AAO_CLIENT_ID")
        if not client_id:
            raise RuntimeError("AAO_CLIENT_ID is required when AAO_PROVIDER=graph")
        tenant = os.environ.get("AAO_TENANT", "common")
        return GraphClient(client_id=client_id, tenant=tenant)
    raise RuntimeError(f"Unknown AAO_PROVIDER: {provider!r} (expected 'gmail' or 'graph')")


def run_sync(client, classifier: Classifier, db: Database, since_iso: str | None) -> dict:
    """Pull messages, classify each, persist results. Pure function given the inputs."""
    counts = {"seen": 0, "classified": 0, "skipped": 0, "recorded": 0, "duplicates": 0}
    for msg in client.fetch_messages_since(since_iso):
        counts["seen"] += 1
        email = _to_email(msg)
        result = classifier.classify(email)
        if result is None:
            counts["skipped"] += 1
            continue
        counts["classified"] += 1
        app_id = db.record_event(
            message_id=email.message_id,
            classification=result,
            occurred_at=email.received_at,
        )
        if app_id is None:
            counts["duplicates"] += 1
        else:
            counts["recorded"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync job-application emails into SQLite.")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Fetch the last 6 months instead of incremental sync.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args(argv)

    configure_logging(args.log_dir)

    provider = os.environ.get("AAO_PROVIDER", DEFAULT_PROVIDER)

    try:
        client = build_client(provider)
    except RuntimeError as err:
        log.error("%s", err)
        return 2

    log.info("Using mail provider: %s", provider)

    db = Database(args.db_path)
    db.init_schema()
    classifier = Classifier.from_yaml(RULES_PATH)

    if args.backfill:
        since = (datetime.now(timezone.utc) - timedelta(days=183)).strftime("%Y-%m-%dT%H:%M:%SZ")
        log.info("Backfill mode: fetching messages since %s", since)
    else:
        since = db.last_event_at()
        log.info("Incremental sync since %s", since or "<beginning>")

    try:
        counts = run_sync(client, classifier, db, since)
    except Exception:
        log.exception("Sync failed")
        return 1

    log.info("Sync complete: %s", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
