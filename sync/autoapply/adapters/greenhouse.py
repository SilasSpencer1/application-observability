from __future__ import annotations
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.models import Listing, Profile

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

# Labels that identify the link-style custom questions Greenhouse forms
# routinely include. Case-insensitive regex, first match wins per field.
_LINKEDIN_LABEL = re.compile(r"linkedin", re.IGNORECASE)
_GITHUB_LABEL = re.compile(r"github", re.IGNORECASE)
_PORTFOLIO_LABEL = re.compile(r"portfolio|website|personal site", re.IGNORECASE)

# Greenhouse marks required labels with a trailing asterisk when the control
# itself doesn't carry the HTML required attribute (common for selects and
# react widgets wrapped in divs).
_REQUIRED_LABEL = re.compile(r"\*\s*$")

# Placeholder option text used by common "Please select" dropdowns. A select
# whose selected option matches any of these is treated as unfilled even if
# its option value is non-empty.
_SELECT_PLACEHOLDER_TEXTS = frozenset(
    {"please select", "select...", "select one", "choose...", "choose", "--"}
)

# Path fragments that signal a Greenhouse-hosted submit went through.
_CONFIRMATION_PATH_MARKERS = ("thanks", "confirmation", "/applications/", "success")

# Greenhouse-the-company hosts their marketing and docs on these subdomains;
# they are not application forms and must not dispatch to this adapter.
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
    """Return names of required fields that are still blank.

    Checks three independent signals, each of which Greenhouse forms rely on:
      1. the HTML `required` attribute on input/select/textarea
      2. `aria-required="true"` on any element (used by react-widget selects)
      3. a <label> whose visible text ends with '*', resolved to its control
         via the `for=` attribute

    Dedupes by element id so a field hit by multiple signals reports once.
    """
    names: list[str] = []
    seen: set[str] = set()

    _collect_from_selector(
        page,
        "input[required]:visible, select[required]:visible, textarea[required]:visible",
        names,
        seen,
    )
    _collect_from_selector(
        page,
        "[aria-required='true']:visible",
        names,
        seen,
    )
    _collect_from_asterisk_labels(page, names, seen)

    return names


def _collect_from_selector(page: "Page", selector: str, names: list[str], seen: set[str]) -> None:
    locator = page.locator(selector)
    for i in range(locator.count()):
        el = locator.nth(i)
        key = _dedup_key(el)
        if key in seen:
            continue
        if not _is_unfilled(el):
            continue
        seen.add(key)
        names.append(_best_field_name(el))


def _collect_from_asterisk_labels(page: "Page", names: list[str], seen: set[str]) -> None:
    labels = page.locator("label")
    for i in range(labels.count()):
        label = labels.nth(i)
        try:
            text = (label.inner_text() or "").strip()
        except Exception:
            continue
        if not _REQUIRED_LABEL.search(text):
            continue
        target_id = label.get_attribute("for")
        if not target_id or f"#{target_id}" in seen:
            continue
        target = page.locator(f"#{target_id}")
        if target.count() == 0:
            continue
        el = target.first
        if not _is_unfilled(el):
            continue
        seen.add(f"#{target_id}")
        names.append(target_id)


def _dedup_key(el: "Locator") -> str:
    el_id = el.get_attribute("id")
    if el_id:
        return f"#{el_id}"
    name = el.get_attribute("name")
    if name:
        return f"name:{name}"
    return f"loc:{id(el)}"


def _is_unfilled(el: "Locator") -> bool:
    try:
        tag = el.evaluate("e => e.tagName.toLowerCase()")
    except Exception:
        return False
    field_type = (el.get_attribute("type") or "").lower()
    # File uploads are handled by the set_input_files call higher up, and the
    # file-input widget does not expose its value via input_value() reliably.
    if tag == "input" and field_type in {"hidden", "submit", "button", "file"}:
        return False
    if tag == "select":
        try:
            selected = el.evaluate(
                "e => { const o = e.options[e.selectedIndex];"
                " return { value: e.value, text: o ? o.text : '' }; }"
            )
        except Exception:
            return False
        value = (selected.get("value") or "").strip()
        text = (selected.get("text") or "").strip().lower()
        if not value:
            return True
        # Non-empty value but the option text matches a known placeholder
        # (some forms use "please select" as both label and value).
        return text in _SELECT_PLACEHOLDER_TEXTS
    if tag in {"input", "textarea"}:
        try:
            value = (el.input_value() or "").strip()
        except Exception:
            return False
        return not value
    # Unknown element (e.g. a div[aria-required]): fall back to text content.
    try:
        text = (el.inner_text() or "").strip()
    except Exception:
        return True
    return not text


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
