from __future__ import annotations
import re
from typing import Iterable, Iterator

from sync.autoapply.models import Listing

# Patterns that disqualify a role title from the "new grad / early career /
# level I" bucket. Any match skips the listing.
_SENIORITY_BLOCKLIST = [
    re.compile(r"\bsenior\b", re.IGNORECASE),
    re.compile(r"\bsr\.?\b", re.IGNORECASE),
    re.compile(r"\bstaff\b", re.IGNORECASE),
    re.compile(r"\bprincipal\b", re.IGNORECASE),
    re.compile(r"\blead\b", re.IGNORECASE),
    re.compile(r"\bmanager\b", re.IGNORECASE),
    re.compile(r"\bdirector\b", re.IGNORECASE),
    re.compile(r"\bvp\b", re.IGNORECASE),
    re.compile(r"\bhead of\b", re.IGNORECASE),
    # Level II / III / IV / V markers.
    re.compile(r"\b(II|III|IV|V)\b"),
    re.compile(r"\bL[2-9]\b"),
    # Internships are out of scope (the SimplifyJobs repo occasionally
    # mislabels an internship as a new-grad role).
    re.compile(r"\bintern(ship)?\b", re.IGNORECASE),
]


def is_entry_level(role: str) -> bool:
    """True when a role title passes the seniority filter.

    The SimplifyJobs repo is already curated to new-grad roles, so this acts
    as a safety net: we block anything that looks senior, mid-level, or
    internship-flavoured rather than requiring a positive keyword match.
    """
    for pattern in _SENIORITY_BLOCKLIST:
        if pattern.search(role):
            return False
    return True


def filter_entry_level(listings: Iterable[Listing]) -> Iterator[Listing]:
    for listing in listings:
        if is_entry_level(listing.role):
            yield listing
