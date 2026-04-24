from pathlib import Path
import os
import pytest

pytest.importorskip("playwright")

from sync.autoapply.adapters.base import ApplyStatus
from sync.autoapply.adapters.ashby import AshbyAdapter
from sync.autoapply.browser import browser_harness
from sync.autoapply.models import Listing, Profile

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ashby_sample.html"


def _make_profile(resume: Path, portfolio: str | None = None) -> Profile:
    return Profile(
        full_name="Jane Middle Smith",
        email="jane@example.com",
        phone="+1 555 555 5555",
        resume_path=resume,
        linkedin_url="https://linkedin.com/in/jane",
        github_url="https://github.com/jane",
        portfolio_url=portfolio,
        school="State U",
        degree="BS",
        major="CS",
        graduation_date="2026-05",
        work_authorized_us=True,
        requires_sponsorship=False,
    )


@pytest.fixture
def resume(tmp_path) -> Path:
    r = tmp_path / "resume.pdf"
    r.write_bytes(b"%PDF-1.4\n%fake\n")
    return r


@pytest.fixture
def listing() -> Listing:
    return Listing(
        company="Notion",
        role="Software Engineer New Grad",
        location="SF",
        apply_url=FIXTURE_PATH.as_uri(),
        source="test",
    )


def test_can_handle_ashby_urls():
    a = AshbyAdapter()
    assert a.can_handle("https://jobs.ashbyhq.com/notion/abc123") is True
    assert a.can_handle("https://jobs.ashbyhq.com/gumloop/xxx/application") is True


def test_can_handle_rejects_non_ashby():
    a = AshbyAdapter()
    assert a.can_handle("https://boards.greenhouse.io/axon/jobs/1") is False
    assert a.can_handle("https://linkedin.com/jobs/view/1") is False


def test_apply_fills_all_known_fields_and_submits(resume, listing):
    profile = _make_profile(resume, portfolio="https://jane.dev")
    adapter = AshbyAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.SUCCESS, result.message


def test_apply_uses_single_name_field(resume, tmp_path):
    # Verify we do NOT split the name and fill fake first/last fields that
    # Ashby does not have. Use a blocker to keep the adapter from clicking
    # submit so we can read the filled state.
    fixture_text = FIXTURE_PATH.read_text().replace(
        '<button type="submit">',
        '<label for="blocker">Blocker *</label>'
        '<input id="blocker" name="blocker" required>'
        '<button type="submit">',
    )
    blocked = tmp_path / "blocked.html"
    blocked.write_text(fixture_text)
    listing = Listing(
        company="Notion", role="SWE", location="SF",
        apply_url=blocked.as_uri(), source="test",
    )
    profile = _make_profile(resume)
    adapter = AshbyAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

        assert result.status is ApplyStatus.NEEDS_REVIEW
        assert page.locator("#ashby_name").input_value() == "Jane Middle Smith"
        assert page.locator("#ashby_email").input_value() == "jane@example.com"
        assert page.locator("#ashby_phone").input_value() == "+1 555 555 5555"
        assert page.locator("#ashby_linkedin").input_value() == "https://linkedin.com/in/jane"
        assert page.locator("#ashby_github").input_value() == "https://github.com/jane"


def test_apply_returns_needs_review_for_missing_required_field(resume, listing):
    # Profile with empty LinkedIn leaves the required #ashby_linkedin blank.
    profile = Profile(
        full_name="Jane Smith",
        email="jane@example.com",
        phone="+1 555 555 5555",
        resume_path=resume,
        linkedin_url="",  # required field left blank
        github_url="https://github.com/jane",
        school="State U",
        degree="BS",
        major="CS",
        graduation_date="2026-05",
        work_authorized_us=True,
        requires_sponsorship=False,
    )
    adapter = AshbyAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert any("linkedin" in f.lower() or "ashby_linkedin" in f for f in result.unfilled_fields)


@pytest.mark.skipif(
    os.environ.get("AAO_RUN_LIVE_TESTS") != "1"
    or not os.environ.get("AAO_LIVE_ASHBY_URL"),
    reason="Live integration test. Set AAO_RUN_LIVE_TESTS=1 and "
           "AAO_LIVE_ASHBY_URL to a real Ashby job URL.",
)
def test_live_ashby_detects_form(resume):
    """Hit a real Ashby job, force NEEDS_REVIEW by leaving LinkedIn blank."""
    url = os.environ["AAO_LIVE_ASHBY_URL"]
    profile = Profile(
        full_name="Test Applicant",
        email="never-sent@example.invalid",
        phone="+1 555 000 0000",
        resume_path=resume,
        linkedin_url="",
        github_url="",
        school="U",
        degree="BS",
        major="CS",
        graduation_date="2030-12",
        work_authorized_us=True,
        requires_sponsorship=False,
    )
    listing = Listing(
        company="LiveCo",
        role="Live Test Role",
        location="Live",
        apply_url=url,
        source="test_live",
    )
    adapter = AshbyAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)
    assert result.status is ApplyStatus.NEEDS_REVIEW, (
        f"expected NEEDS_REVIEW on a real Ashby form with blank LinkedIn, "
        f"got {result.status.value}: {result.message}"
    )
