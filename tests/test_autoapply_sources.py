from pathlib import Path
import os
import pytest

from sync.autoapply.sources.simplify_repo import (
    SimplifyReadmeSource,
    parse_listings,
    SOURCE_NAME,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "simplify_new_grad_snippet.md"


@pytest.fixture
def snippet_text() -> str:
    return FIXTURE_PATH.read_text()


def test_parse_listings_returns_expected_rows(snippet_text):
    listings = list(parse_listings(snippet_text))
    companies = [l.company for l in listings]
    # Axon, Notion, Western Alliance, Western Alliance (continuation),
    # Gumloop, SeniorCorp, Daimler Truck. ClosedCorp is skipped because of 🔒.
    assert companies == [
        "Axon",
        "Notion",
        "Western Alliance",
        "Western Alliance",
        "Gumloop",
        "SeniorCorp",
        "Daimler Truck",
    ]


def test_parse_listings_extracts_apply_and_simplify_urls(snippet_text):
    axon = next(l for l in parse_listings(snippet_text) if l.company == "Axon")
    assert axon.apply_url.startswith("https://job-boards.greenhouse.io/axon")
    assert axon.simplify_url == "https://simplify.jobs/p/4d0cb5cc-4412-46d1-a116-216e3a4f8f44?utm_source=GHList"
    assert axon.role == "Software Engineer 1"
    assert axon.location == "Seattle, WA"
    assert axon.source == SOURCE_NAME


def test_parse_listings_strips_company_emoji(snippet_text):
    notion = next(l for l in parse_listings(snippet_text) if l.company == "Notion")
    assert notion.company == "Notion"  # 🔥 stripped
    assert notion.apply_url.startswith("https://jobs.ashbyhq.com/notion")


def test_parse_listings_uses_last_company_for_continuation(snippet_text):
    wab = [l for l in parse_listings(snippet_text) if l.company == "Western Alliance"]
    assert len(wab) == 2
    # Apply URLs differ for the two roles.
    assert wab[0].apply_url != wab[1].apply_url
    # Continuation row merges multi-location </br> into a single string.
    assert "/" in wab[1].location


def test_parse_listings_skips_closed_rows(snippet_text):
    companies = [l.company for l in parse_listings(snippet_text)]
    assert "ClosedCorp" not in companies


def test_parse_listings_handles_company_without_anchor(snippet_text):
    gumloop = next(l for l in parse_listings(snippet_text) if l.company == "Gumloop")
    # No anchor link on the company, but role and apply_url still present.
    assert gumloop.role == "Software Engineer"
    assert "ashbyhq.com/gumloop" in gumloop.apply_url
    # No Simplify link in this row so simplify_url is None.
    assert gumloop.simplify_url is None


def test_parse_listings_multi_location_uses_slash_separator(snippet_text):
    gumloop = next(l for l in parse_listings(snippet_text) if l.company == "Gumloop")
    assert gumloop.location == "San Francisco, CA / Vancouver, BC, CAN"


def test_parse_listings_ignores_senior_roles_too_filter_is_not_in_parser(snippet_text):
    # Seniority filtering belongs to filter.py. The parser should still yield
    # a SeniorCorp listing; it's the caller's job to drop it later.
    companies = [l.company for l in parse_listings(snippet_text)]
    assert "SeniorCorp" in companies


def test_source_uses_injected_fetch(snippet_text):
    source = SimplifyReadmeSource(fetch=lambda url: snippet_text)
    listings = source.listings()
    assert len(listings) >= 5
    assert all(l.apply_url for l in listings)


def test_source_requires_non_empty_role(snippet_text):
    # Synthetic row with an empty role cell should be skipped.
    empty_role_row = """
<tr>
<td><strong>Nothing</strong></td>
<td></td>
<td>Nowhere</td>
<td><a href="https://example.com/apply">Apply</a></td>
<td>0d</td>
</tr>
"""
    listings = list(parse_listings(empty_role_row))
    assert listings == []


def test_source_requires_apply_url(snippet_text):
    # Row with only a Simplify link and no direct ATS link should be skipped.
    row = """
<tr>
<td><strong>SimplifyOnlyCo</strong></td>
<td>Software Engineer</td>
<td>Remote</td>
<td><a href="https://simplify.jobs/p/xxx">Simplify</a></td>
<td>0d</td>
</tr>
"""
    assert list(parse_listings(row)) == []


@pytest.mark.skipif(
    os.environ.get("AAO_RUN_LIVE_TESTS") != "1",
    reason="Live network test. Set AAO_RUN_LIVE_TESTS=1 to enable.",
)
def test_live_fetch_from_github():
    """Integration test hitting the real SimplifyJobs README.

    Skipped by default so unit runs stay hermetic. To run:
        AAO_RUN_LIVE_TESTS=1 pytest tests/test_autoapply_sources.py -k live
    """
    source = SimplifyReadmeSource()
    listings = source.listings()
    assert len(listings) > 50, "expected the real repo to have many listings"
    assert all(l.apply_url for l in listings)
    assert any(l.simplify_url for l in listings), "expected at least one simplify URL"
    assert all(l.source == SOURCE_NAME for l in listings)
