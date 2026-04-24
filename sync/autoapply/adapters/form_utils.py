"""Form-filling helpers shared across ATS adapters.

Adapters live in separate files (greenhouse.py, ashby.py, ...) because
every ATS has its own field naming and page layout. These helpers cover
the parts that are genuinely shared: finding required fields that are
still blank, reading if a control has been filled, and picking a
stable name for a control when reporting back to the runner.
"""
from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

# Label patterns for common link-style custom questions. Case-insensitive.
LINKEDIN_LABEL = re.compile(r"linkedin", re.IGNORECASE)
GITHUB_LABEL = re.compile(r"github", re.IGNORECASE)
PORTFOLIO_LABEL = re.compile(r"portfolio|website|personal site", re.IGNORECASE)

# Matches a label whose visible text ends with '*'. Used as a required-field
# signal when the control itself carries neither required nor aria-required.
REQUIRED_LABEL_RE = re.compile(r"\*\s*$")

# Option text commonly used as a placeholder in required <select> controls.
# A select whose selected option's text is one of these is treated as
# unfilled even when its option value is non-empty (e.g. "0").
SELECT_PLACEHOLDER_TEXTS = frozenset(
    {"please select", "select...", "select one", "choose...", "choose", "--"}
)


def required_fields_left_unfilled(page: "Page") -> list[str]:
    """Return names of visible required fields that are still blank.

    Three independent signals, each of which ATS forms rely on:
      1. HTML `required` attribute on input/select/textarea
      2. `aria-required='true'` on any element (react widget selects)
      3. a <label> whose visible text ends with '*', resolved to its
         control via the `for=` attribute

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
    _collect_from_selector(page, "[aria-required='true']:visible", names, seen)
    _collect_from_asterisk_labels(page, names, seen)

    return names


def is_unfilled(el: "Locator") -> bool:
    """True when a control has no meaningful user-supplied value.

    Handles selects with placeholder options, file inputs (delegated to the
    adapter's set_input_files call), and generic input/textarea.
    """
    try:
        tag = el.evaluate("e => e.tagName.toLowerCase()")
    except Exception:
        return False
    field_type = (el.get_attribute("type") or "").lower()
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
        return text in SELECT_PLACEHOLDER_TEXTS
    if tag in {"input", "textarea"}:
        try:
            value = (el.input_value() or "").strip()
        except Exception:
            return False
        return not value
    try:
        text = (el.inner_text() or "").strip()
    except Exception:
        return True
    return not text


def best_field_name(el: "Locator") -> str:
    """Pick a stable, user-facing name for a control."""
    for attr in ("aria-label", "name", "id"):
        v = el.get_attribute(attr)
        if v:
            return v
    return "<unnamed>"


def fill_by_label(page: "Page", label_pattern: re.Pattern, value: str) -> None:
    """Fill the first control whose associated label matches the regex.

    Silently no-ops when the label isn't on the page or the control can't
    be resolved, since most ATS forms include only a subset of the common
    link-style questions (LinkedIn, GitHub, portfolio).
    """
    try:
        locator = page.get_by_label(label_pattern)
    except Exception:
        return
    if locator.count() > 0:
        locator.first.fill(value)


def _collect_from_selector(
    page: "Page", selector: str, names: list[str], seen: set[str]
) -> None:
    locator = page.locator(selector)
    for i in range(locator.count()):
        el = locator.nth(i)
        key = _dedup_key(el)
        if key in seen:
            continue
        if not is_unfilled(el):
            continue
        seen.add(key)
        names.append(best_field_name(el))


def _collect_from_asterisk_labels(
    page: "Page", names: list[str], seen: set[str]
) -> None:
    labels = page.locator("label")
    for i in range(labels.count()):
        label = labels.nth(i)
        try:
            text = (label.inner_text() or "").strip()
        except Exception:
            continue
        if not REQUIRED_LABEL_RE.search(text):
            continue
        target_id = label.get_attribute("for")
        if not target_id or f"#{target_id}" in seen:
            continue
        target = page.locator(f"#{target_id}")
        if target.count() == 0:
            continue
        if not is_unfilled(target.first):
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
