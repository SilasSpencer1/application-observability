from __future__ import annotations
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.models import Listing, Profile

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

_GREENHOUSE_HOSTS = ("greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io")

# Labels that identify the link-style custom questions Greenhouse forms
# routinely include. Case-insensitive regex, first match wins per field.
_LINKEDIN_LABEL = re.compile(r"linkedin", re.IGNORECASE)
_GITHUB_LABEL = re.compile(r"github", re.IGNORECASE)
_PORTFOLIO_LABEL = re.compile(r"portfolio|website|personal site", re.IGNORECASE)

# Greenhouse marks required labels with a trailing asterisk or an aria-required attr.
_REQUIRED_LABEL = re.compile(r"\*\s*$")


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
        return any(host == h or host.endswith("." + h) for h in _GREENHOUSE_HOSTS)

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

        _fill_by_label(page, _LINKEDIN_LABEL, profile.linkedin_url)
        _fill_by_label(page, _GITHUB_LABEL, profile.github_url)
        if profile.portfolio_url:
            _fill_by_label(page, _PORTFOLIO_LABEL, profile.portfolio_url)

        unfilled = _required_fields_left_unfilled(page)
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


def _fill_by_label(page: "Page", label_pattern: re.Pattern, value: str) -> None:
    try:
        locator = page.get_by_label(label_pattern)
    except Exception:
        return
    if locator.count() > 0:
        locator.first.fill(value)


def _required_fields_left_unfilled(page: "Page") -> list[str]:
    """Return labels (or id fallbacks) of required fields that are still blank."""
    names: list[str] = []
    inputs = page.locator(
        "input[required]:visible, select[required]:visible, textarea[required]:visible"
    )
    for i in range(inputs.count()):
        el = inputs.nth(i)
        field_type = (el.get_attribute("type") or "").lower()
        if field_type in {"hidden", "submit", "button"}:
            continue
        if field_type == "file":
            # Playwright cannot read input_value on a file field; assume the
            # set_input_files call above handled it.
            continue
        value = (el.input_value() or "").strip()
        if value:
            continue
        names.append(_best_field_name(el))
    return names


def _best_field_name(el: "Locator") -> str:
    for attr in ("aria-label", "name", "id"):
        v = el.get_attribute(attr)
        if v:
            return v
    return "<unnamed>"


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
    """Best-effort signal that Greenhouse accepted the submission.

    Greenhouse's hosted forms redirect to a URL containing 'thanks',
    'confirmation', or an application id path segment. For local-fixture
    tests a post-submit page with a confirmation element works too.
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    if page.url != before_url:
        return True
    confirmation = page.locator("[data-testid='confirmation'], .confirmation, #confirmation")
    return confirmation.count() > 0
