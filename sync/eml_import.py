from __future__ import annotations
import argparse
import email
import email.policy
import hashlib
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from sync.classifier import Classifier, Email
from sync.db import Database
from sync.sync import (
    DEFAULT_DB_PATH,
    DEFAULT_LOG_DIR,
    RULES_PATH,
    configure_logging,
)

log = logging.getLogger("eml_import")


@dataclass
class ImportCounts:
    seen: int = 0
    classified: int = 0
    skipped: int = 0
    recorded: int = 0
    duplicates: int = 0
    unknown_baseline: int = 0


def _normalize_date_header(raw: str | None) -> str:
    """Convert an RFC 2822 Date header into the canonical UTC ISO form."""
    if not raw:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_plain_text(msg) -> str:
    """Walk the MIME tree and return the first text/plain body, falling back
    to text/html if that's all the email carries."""
    def pick(part, target_mime: str) -> str:
        if part.get_content_type() == target_mime:
            try:
                return part.get_content()
            except Exception:
                raw = part.get_payload(decode=True) or b""
                return raw.decode("utf-8", errors="replace")
        for child in part.iter_parts() if part.is_multipart() else []:
            got = pick(child, target_mime)
            if got:
                return got
        return ""

    if msg.is_multipart():
        return pick(msg, "text/plain") or pick(msg, "text/html")
    try:
        return msg.get_content() if msg.get_content_type().startswith("text/") else ""
    except Exception:
        raw = msg.get_payload(decode=True) or b""
        return raw.decode("utf-8", errors="replace")


def parse_eml(path: Path) -> Email:
    """Parse an .eml file on disk into our canonical Email dataclass."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    msg = email.message_from_string(raw, policy=email.policy.default)
    from_name, from_address = parseaddr(msg.get("from", ""))
    message_id = msg.get("message-id")
    if not message_id:
        # Some exports drop this header, so fall back to a content-stable hash.
        digest = hashlib.sha1(f"{path.name}:{msg.get('subject','')}".encode()).hexdigest()[:16]
        message_id = f"eml-{digest}"
    return Email(
        message_id=message_id.strip("<> "),
        subject=msg.get("subject", "") or "",
        from_name=from_name or "",
        from_address=from_address or "",
        body=_first_plain_text(msg) or "",
        received_at=_normalize_date_header(msg.get("date")),
    )


def _resolve_paths(inputs: list[Path]) -> list[Path]:
    """Expand directories into their .eml files, leaving file paths as-is."""
    resolved: list[Path] = []
    for p in inputs:
        if p.is_dir():
            resolved.extend(sorted(p.glob("*.eml")))
        elif p.suffix.lower() == ".eml" and p.is_file():
            resolved.append(p)
    return resolved


def import_files(
    paths: list[Path],
    classifier: Classifier,
    db: Database,
) -> ImportCounts:
    counts = ImportCounts()
    for path in paths:
        counts.seen += 1
        try:
            email_obj = parse_eml(path)
        except Exception:
            log.exception("Failed to parse %s", path)
            counts.skipped += 1
            continue
        result = classifier.classify(email_obj)
        if result is None:
            log.info("Skipping %s: classifier found no job status", path.name)
            counts.skipped += 1
            continue
        counts.classified += 1
        if result.status != "applied":
            counts.unknown_baseline += 1
        app_id = db.record_event(
            message_id=email_obj.message_id,
            classification=result,
            occurred_at=email_obj.received_at,
            allow_unknown_applied_at=True,
        )
        if app_id is None:
            counts.duplicates += 1
        else:
            counts.recorded += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import one or more .eml files (or a directory of them) into the "
            "local database. Decision-only emails create an application row "
            "with an unknown applied_at."
        )
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Paths to .eml files or directories containing them.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args(argv)

    configure_logging(args.log_dir)
    files = _resolve_paths(args.paths)
    if not files:
        log.error("No .eml files found under: %s", ", ".join(str(p) for p in args.paths))
        return 2

    db = Database(args.db_path)
    db.init_schema()
    classifier = Classifier.from_yaml(RULES_PATH)

    counts = import_files(files, classifier, db)
    log.info("Import complete: %s", counts)
    print(
        f"Seen {counts.seen}, recorded {counts.recorded}, duplicates {counts.duplicates}, "
        f"skipped {counts.skipped}, unknown-baseline {counts.unknown_baseline}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
