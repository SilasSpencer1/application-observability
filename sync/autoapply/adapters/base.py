from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from sync.autoapply.models import Listing, Profile

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ApplyStatus(str, Enum):
    """Outcome of a single adapter.apply() call."""
    SUCCESS = "success"             # form submitted, confirmation observed
    FAILED = "failed"               # unrecoverable error (page load, etc.)
    NEEDS_REVIEW = "needs_review"   # required field left blank, submit skipped
    SKIPPED = "skipped"             # adapter chose not to submit (e.g. bad URL)


@dataclass(frozen=True)
class ApplyResult:
    status: ApplyStatus
    url: str
    message: str | None = None
    unfilled_fields: tuple[str, ...] = field(default_factory=tuple)


class Adapter(ABC):
    """A per-ATS form filler.

    Implementations are stateless and cheap to construct. The runner gives
    each adapter a Playwright page already navigated or about to navigate
    to listing.apply_url, plus the user's Profile. The adapter drives the
    form and returns an ApplyResult. The runner owns browser lifecycle.
    """
    name: str = "base"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this adapter recognises the URL's ATS."""

    @abstractmethod
    def apply(self, page: "Page", listing: Listing, profile: Profile) -> ApplyResult:
        """Navigate, fill, submit (or defer), and report."""
