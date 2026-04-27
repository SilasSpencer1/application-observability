from __future__ import annotations
import re
from typing import Callable, Iterable

import requests

from sync.autoapply.models import Listing
from sync.autoapply.sources.base import ListingSource

SIMPLIFY_README_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"
)

SOURCE_NAME = "simplify_new_grad"

_TR_RE = re.compile(r"<tr>\s*(.*?)\s*</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]+)"')
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Any <br>, <BR>, <br/>, <br class="...">, or </br>, used to split a cell
# that holds multiple locations into newline-separated parts before tags
# are stripped.
_BR_RE = re.compile(r"<\s*/?\s*br\s*[^>]*>", re.IGNORECASE)

# Prefix emoji the Simplify legend uses on company names.
_COMPANY_EMOJI = ("🔥", "🛂", "🇺🇸", "🎓", "🔒")

# "Same company as above" continuation marker. Simplify uses U+21B3.
_CONTINUATION_MARKERS = {"↳"}


class SimplifyReadmeSource(ListingSource):
    """Parse listings from the SimplifyJobs/New-Grad-Positions README.

    The README is maintained by Simplify as raw HTML tables inside a markdown
    file. Rows follow:
        <td>Company anchor</td>
        <td>Role text</td>
        <td>Location</td>
        <td>Apply anchor + Simplify anchor</td>
        <td>Age (e.g. '0d')</td>
    Continuation rows use '↳' in the company cell to mean 'same as above'.
    Closed listings are tagged with 🔒 in the company cell.
    """

    def __init__(
        self,
        url: str = SIMPLIFY_README_URL,
        fetch: Callable[[str], str] | None = None,
    ):
        self.url = url
        self._fetch = fetch

    def _fetch_text(self) -> str:
        if self._fetch is not None:
            return self._fetch(self.url)
        resp = requests.get(self.url, timeout=30)
        resp.raise_for_status()
        return resp.text

    def listings(self) -> list[Listing]:
        return list(parse_listings(self._fetch_text()))


def parse_listings(text: str) -> Iterable[Listing]:
    last_company: str | None = None
    for tr in _TR_RE.finditer(text):
        cells = _TD_RE.findall(tr.group(1))
        if len(cells) < 4:
            continue

        company_cell, role_cell, location_cell, apply_cell = cells[:4]

        company = _extract_company(company_cell, last_company)
        if company is None:
            continue
        last_company = company

        if _is_closed(company_cell):
            continue

        role = _clean_text(role_cell)
        if not role:
            continue

        apply_url = _first_href_matching(apply_cell, exclude_simplify=True)
        simplify_url = _first_href_matching(apply_cell, exclude_simplify=False, only_simplify=True)
        if not apply_url:
            continue

        yield Listing(
            company=company,
            role=role,
            location=_clean_location(location_cell),
            apply_url=apply_url,
            simplify_url=simplify_url,
            source=SOURCE_NAME,
        )


def _extract_company(cell: str, last_company: str | None) -> str | None:
    text = _clean_text(cell)
    if text in _CONTINUATION_MARKERS:
        return last_company
    for emoji in _COMPANY_EMOJI:
        text = text.replace(emoji, "")
    text = text.strip()
    return text or None


def _is_closed(cell: str) -> bool:
    return "🔒" in cell


def _clean_text(html: str) -> str:
    text = _HTML_TAG_RE.sub("", html)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _clean_location(cell: str) -> str | None:
    expanded = _BR_RE.sub("\n", cell)
    text = _HTML_TAG_RE.sub("", expanded)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return " / ".join(lines)


def _first_href_matching(
    cell: str, *, exclude_simplify: bool = False, only_simplify: bool = False
) -> str | None:
    # Order-dependent: Simplify conventionally places the ATS anchor first
    # and the simplify.jobs/p/ redirect second. If that order flips, the
    # exclude_simplify path still does the right thing but only_simplify
    # would return the correct (Simplify) URL regardless of position.
    for href in _HREF_RE.findall(cell):
        is_simplify = "simplify.jobs/p/" in href
        if only_simplify and not is_simplify:
            continue
        if exclude_simplify and is_simplify:
            continue
        return href
    return None
