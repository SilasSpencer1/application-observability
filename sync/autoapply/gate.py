from __future__ import annotations
from datetime import datetime, timedelta, timezone

from sync.db import Database

REJECTED_COOLDOWN_DAYS = 210  # roughly 7 months

# Statuses that permanently block reapplication for the same (company, role).
# Kept as a frozenset so adding a new status later (e.g. 'withdrawn') is a
# single-line change and the intent is obvious at call sites.
TERMINAL_STATUSES = frozenset({"applied", "next_step", "offer"})


class AutoApplyGate:
    """Decide whether to auto-apply to a (company, role) pair.

    Rules, in order:
      1. If a row exists for (company, role) with current_status in
         TERMINAL_STATUSES, return False. We never reapply.
      2. If the row exists with current_status = 'rejected', return False
         until at least REJECTED_COOLDOWN_DAYS after status_updated_at.
      3. Otherwise, return True.
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
        if status in TERMINAL_STATUSES:
            return False
        if status == "rejected":
            cooldown_ends = _parse_iso(row["status_updated_at"]) + timedelta(
                days=REJECTED_COOLDOWN_DAYS
            )
            return self._current_time() >= cooldown_ends
        return True


def _parse_iso(value: str) -> datetime:
    # DB stores ISO 8601, usually with a 'Z' suffix. Normalize 'Z' -> '+00:00'
    # for older Python compatibility, then force UTC on any naive string so
    # the comparison against an aware self._current_time() never TypeErrors.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
