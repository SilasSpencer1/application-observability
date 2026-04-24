from __future__ import annotations
from datetime import datetime, timedelta, timezone

from sync.db import Database

REJECTED_COOLDOWN_DAYS = 210  # roughly 7 months


class AutoApplyGate:
    """Decide whether to auto-apply to a (company, role) pair.

    Rules, in order:
      1. If a row exists for (company, role) with current_status in
         ('applied', 'next_step', 'offer'), skip. We never reapply.
      2. If the row exists with current_status = 'rejected', skip until
         at least REJECTED_COOLDOWN_DAYS after status_updated_at.
      3. Otherwise, apply.
    """

    def __init__(self, db: Database, now: datetime | None = None):
        self.db = db
        self._now = now

    def _current_time(self) -> datetime:
        return self._now or datetime.now(tz=timezone.utc)

    def should_apply(self, company: str, role: str | None) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT current_status, status_updated_at FROM applications "
                "WHERE company = ? AND COALESCE(role, '') = COALESCE(?, '')",
                (company, role),
            ).fetchone()
        if row is None:
            return True
        status = row["current_status"]
        if status in ("applied", "next_step", "offer"):
            return False
        if status == "rejected":
            cooldown_ends = _parse_iso(row["status_updated_at"]) + timedelta(
                days=REJECTED_COOLDOWN_DAYS
            )
            return self._current_time() >= cooldown_ends
        return True


def _parse_iso(value: str) -> datetime:
    # DB stores ISO 8601, sometimes with a 'Z' suffix. datetime.fromisoformat
    # accepts 'Z' on 3.11+, but we normalize defensively in case older rows
    # carry a different format.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
