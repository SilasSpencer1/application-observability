from __future__ import annotations
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.adapters.form_utils import (
    GITHUB_LABEL,
    LINKEDIN_LABEL,
    PORTFOLIO_LABEL,
    fill_by_label,
    required_fields_left_unfilled,
)
from sync.autoapply.models import Listing, Profile

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Ashby puts the whole legal name in one field, so we match "Name" or
# "Full Name" but not "First Name" / "Last Name". Trailing asterisk is
# accepted because Ashby renders the required-marker inside the label.
_NAME_LABEL = re.compile(r"^(full\s+)?name\s*\*?\s*$", re.IGNORECASE)
_EMAIL_LABEL = re.compile(r"^email\s*\*?\s*$", re.IGNORECASE)
_PHONE_LABEL = re.compile(r"phone", re.IGNORECASE)


class AshbyAdapter(Adapter):
    """Fill and submit an Ashby-hosted application form.

    Handles jobs.ashbyhq.com forms. Ashby renders fields label-bound
    without predictable ids, so the adapter uses label patterns for
    identity and link-style custom questions. Required-field detection
    reuses the shared helper in form_utils.
    """
    name = "ashby"

    def can_handle(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com")

    def apply(self, page: "Page", listing: Listing, profile: Profile) -> ApplyResult:
        try:
            page.goto(listing.apply_url, wait_until="domcontentloaded", timeout=30_000)
            # Ashby is an SPA; wait for the form shell to render before we
            # start filling. Either a file input or a submit button shows up
            # once the React app mounts.
            page.wait_for_selector(
                "input[type='file'], button[type='submit']", timeout=20_000
            )
        except Exception as e:
            return ApplyResult(
                status=ApplyStatus.FAILED,
                url=listing.apply_url,
                message=f"page did not load: {e}",
            )

        fill_by_label(page, _NAME_LABEL, profile.full_name)
        fill_by_label(page, _EMAIL_LABEL, profile.email)
        fill_by_label(page, _PHONE_LABEL, profile.phone)

        resume_input = page.locator("input[type='file']").first
        if resume_input.count() > 0:
            resume_input.set_input_files(str(profile.resume_path))

        fill_by_label(page, LINKEDIN_LABEL, profile.linkedin_url)
        fill_by_label(page, GITHUB_LABEL, profile.github_url)
        if profile.portfolio_url:
            fill_by_label(page, PORTFOLIO_LABEL, profile.portfolio_url)

        unfilled = required_fields_left_unfilled(page)
        if unfilled:
            return ApplyResult(
                status=ApplyStatus.NEEDS_REVIEW,
                url=listing.apply_url,
                message="required fields left unfilled; handing to fallback",
                unfilled_fields=tuple(unfilled),
            )

        submit = _find_submit_button(page)
        if submit is None:
            return ApplyResult(
                status=ApplyStatus.FAILED,
                url=listing.apply_url,
                message="submit button not found",
            )

        before_url = page.url
        try:
            submit.click()
        except Exception as e:
            return ApplyResult(
                status=ApplyStatus.FAILED,
                url=listing.apply_url,
                message=f"submit click failed: {e}",
            )

        if _submitted(page, before_url):
            return ApplyResult(status=ApplyStatus.SUCCESS, url=page.url)
        return ApplyResult(
            status=ApplyStatus.FAILED,
            url=listing.apply_url,
            message="no confirmation state after submit",
        )


def _find_submit_button(page: "Page"):
    # Ashby uses text rather than stable ids on the submit control.
    selectors = (
        "button:has-text('Submit Application')",
        "button[type='submit']",
    )
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.first
    return None


def _submitted(page: "Page", before_url: str) -> bool:
    """Signal that Ashby accepted the submission.

    Ashby is an SPA: the URL typically stays the same after submit and the
    form gets replaced by a 'Thanks for applying' / 'Application submitted'
    block. Wait for either a known confirmation container or that text to
    appear, with a short timeout. CSS and text locators cannot be mixed in
    a single comma selector, so we chain them with .or_().
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    confirmation = (
        page.locator(".ashby-application-submitted")
        .or_(page.locator(".ashby-job-application-submitted-container"))
        .or_(page.locator("[data-testid='submitted']"))
        .or_(page.get_by_text(
            re.compile(
                r"Thanks for applying|Application submitted|Your application has been received",
                re.IGNORECASE,
            )
        ))
    )
    try:
        confirmation.first.wait_for(timeout=15_000)
        return True
    except Exception:
        return False
