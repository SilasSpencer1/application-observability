from __future__ import annotations
from typing import TYPE_CHECKING, Sequence

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.models import Listing, Profile

if TYPE_CHECKING:
    from playwright.sync_api import Page


class AdapterDispatcher:
    """Pick the right ATS adapter for a listing and fall back when it fails.

    The dispatcher tries each adapter in order and uses the first one whose
    can_handle(url) returns True. If that adapter returns SUCCESS, the
    dispatcher returns it unchanged. If it returns anything else (FAILED,
    NEEDS_REVIEW), or raises, the dispatcher hands the listing to the
    fallback adapter (the Simplify-extension driver in a later PR).

    When no adapter matches and a fallback is configured, the fallback
    runs. When no fallback is configured and nothing matches, the result
    is SKIPPED so the runner can log and move on.
    """

    def __init__(self, adapters: Sequence[Adapter], fallback: Adapter | None = None):
        self.adapters = list(adapters)
        self.fallback = fallback

    def pick(self, url: str) -> Adapter | None:
        for adapter in self.adapters:
            if adapter.can_handle(url):
                return adapter
        return None

    def apply(self, page: "Page", listing: Listing, profile: Profile) -> ApplyResult:
        adapter = self.pick(listing.apply_url)

        if adapter is None:
            if self.fallback is not None:
                return self.fallback.apply(page, listing, profile)
            return ApplyResult(
                status=ApplyStatus.SKIPPED,
                url=listing.apply_url,
                message="no adapter matched this URL",
            )

        result = _run_adapter(adapter, page, listing, profile)
        if result.status is ApplyStatus.SUCCESS:
            return result
        if self.fallback is None:
            return result
        return self.fallback.apply(page, listing, profile)


def _run_adapter(
    adapter: Adapter, page: "Page", listing: Listing, profile: Profile
) -> ApplyResult:
    try:
        return adapter.apply(page, listing, profile)
    except Exception as e:
        return ApplyResult(
            status=ApplyStatus.FAILED,
            url=listing.apply_url,
            message=f"{adapter.name} raised: {e}",
        )
