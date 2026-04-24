from __future__ import annotations
import argparse
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sync.classifier import Classification
from sync.db import Database
from sync.sync import DEFAULT_DB_PATH, DEFAULT_LOG_DIR, configure_logging

log = logging.getLogger("add_job")

VALID_STATUSES = ("applied", "next_step", "rejected", "offer")


def _normalize_date(raw: str | None) -> str | None:
    """Accept YYYY-MM-DD or a full ISO 8601 timestamp and emit canonical UTC."""
    if raw is None:
        return None
    try:
        if len(raw) == 10:
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            cleaned = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except ValueError as err:
        raise SystemExit(f"Could not parse date {raw!r}: {err}") from err
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add a single application to the local database by hand."
    )
    parser.add_argument("--company", required=True)
    parser.add_argument("--role", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument(
        "--status",
        choices=VALID_STATUSES,
        default="applied",
        help="Current status of the application. Defaults to 'applied'.",
    )
    parser.add_argument(
        "--applied-at",
        default=None,
        help="When the application went out, as YYYY-MM-DD or ISO 8601. "
        "Leave blank if you don't know.",
    )
    parser.add_argument(
        "--occurred-at",
        default=None,
        help="When the status event happened. Defaults to now.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args(argv)

    configure_logging(args.log_dir)

    applied_at = _normalize_date(args.applied_at)
    occurred_at = _normalize_date(args.occurred_at) or applied_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # A stable fake message id so re-running with the same inputs is a no-op.
    fingerprint = f"manual:{args.company}:{args.role}:{args.status}:{occurred_at}".encode()
    message_id = f"manual-{hashlib.sha1(fingerprint).hexdigest()[:16]}"

    db = Database(args.db_path)
    db.init_schema()

    classification = Classification(
        status=args.status,
        company=args.company,
        role=args.role,
        location=args.location,
    )

    # If the user supplied --applied-at for a non-applied event, we still want
    # to record that ground truth on the application row. Do it by seeding a
    # synthetic applied event first, then the real status event.
    if args.status != "applied" and applied_at:
        seed_id = f"manual-seed-{hashlib.sha1(fingerprint + b':seed').hexdigest()[:16]}"
        db.record_event(
            message_id=seed_id,
            classification=Classification(
                status="applied",
                company=args.company,
                role=args.role,
                location=args.location,
            ),
            occurred_at=applied_at,
        )

    app_id = db.record_event(
        message_id=message_id,
        classification=classification,
        occurred_at=occurred_at,
        allow_unknown_applied_at=True,
    )
    if app_id is None:
        print("No change (duplicate event)")
        return 1
    print(
        f"Recorded app {app_id}: {args.company} / {args.role or '(no role)'} "
        f"status={args.status} at {occurred_at}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
