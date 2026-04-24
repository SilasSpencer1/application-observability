from __future__ import annotations
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

# Path fragments that signal a Greenhouse submission went through.
_CONFIRMATION_PATH_MARKERS = ("thanks", "confirmation", "/applications/", "success")

# Greenhouse markets and blogs from these subdomains; they are not
# application forms and must not dispatch to this adapter.
_GREENHOUSE_MARKETING_HOSTS = frozenset(
    {"www.greenhouse.io", "blog.greenhouse.io", "help.greenhouse.io", "about.greenhouse.io"}
)


class GreenhouseAdapter(Adapter):
    """Fill and submit a Greenhouse-hosted application form.

    Handles the standard hosted forms at boards.greenhouse.io and
    job-boards.greenhouse.io. Identifies core fields by id
    (first_name, last_name, email, phone, resume) and link-style
    custom questions (LinkedIn, GitHub, portfolio) by label.

    If any visible required field is still blank after filling, the
    adapter returns NEEDS_REVIEW without clicking submit so the
    dispatcher can hand the listing to the Simplify fallback.
    """
    name = "greenhouse"

    def can_handle(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        if host in _GREENHOUSE_MARKETING_HOSTS:
            return False
        return host.endswith(".greenhouse.io")

    def apply(self, page: "Page", listing: Listing, profile: Profile) -> ApplyResult:
        try:
            page.goto(listing.apply_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            return ApplyResult(
                status=ApplyStatus.FAILED,
                url=listing.apply_url,
                message=f"page did not load: {e}",
            )

        first_name, last_name = _split_name(profile.full_name)

        _fill_by_id(page, "first_name", first_name)
        _fill_by_id(page, "last_name", last_name)
        _fill_by_id(page, "email", profile.email)
        _fill_by_id(page, "phone", profile.phone)

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


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _fill_by_id(page: "Page", field_id: str, value: str) -> None:
    locator = page.locator(f"#{field_id}")
    if locator.count() > 0:
        locator.first.fill(value)


def _find_submit_button(page: "Page"):
    selectors = (
        "#submit_app",
        "button[type='submit']",
        "input[type='submit']",
    )
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.first
    return None


def _submitted(page: "Page", before_url: str) -> bool:
    """Signal that Greenhouse accepted the submission.

    A bare URL change is not enough: Greenhouse validation errors can
    redirect to an error page on the same path. We require either a
    known-confirmation path marker on a changed URL, or a confirmation
    element on the post-submit page.
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    url = page.url
    if url != before_url and any(m in url for m in _CONFIRMATION_PATH_MARKERS):
        return True
    confirmation = page.locator(
        "[data-testid='confirmation'], .confirmation, #confirmation"
    )
    return confirmation.count() > 0
