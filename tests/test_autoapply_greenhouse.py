from pathlib import Path
import os
import pytest

pytest.importorskip("playwright")

from sync.autoapply.adapters.base import ApplyStatus
from sync.autoapply.adapters.greenhouse import GreenhouseAdapter
from sync.autoapply.browser import browser_harness
from sync.autoapply.models import Listing, Profile

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "greenhouse_sample.html"


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
        company="Axon",
        role="Software Engineer I",
        location="Seattle, WA",
        apply_url=FIXTURE_PATH.as_uri(),
        source="test",
    )


def test_can_handle_greenhouse_hosts():
    a = GreenhouseAdapter()
    assert a.can_handle("https://boards.greenhouse.io/axon/jobs/1") is True
    assert a.can_handle("https://job-boards.greenhouse.io/notion/jobs/2") is True
    assert a.can_handle("https://axon.greenhouse.io/jobs/3") is True


def test_can_handle_rejects_other_hosts():
    a = GreenhouseAdapter()
    assert a.can_handle("https://jobs.ashbyhq.com/notion/xxx") is False
    assert a.can_handle("https://linkedin.com/jobs/view/123") is False


def test_can_handle_rejects_marketing_hosts():
    # The marketing, blog, and docs subdomains must not dispatch here.
    a = GreenhouseAdapter()
    assert a.can_handle("https://greenhouse.io/") is False
    assert a.can_handle("https://www.greenhouse.io/careers") is False
    assert a.can_handle("https://blog.greenhouse.io/post") is False
    assert a.can_handle("https://help.greenhouse.io/article") is False


def test_apply_fills_all_known_fields_and_submits(resume, listing):
    profile = _make_profile(resume, portfolio="https://jane.dev")
    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.SUCCESS, result.message


def test_apply_fills_fields_correctly_on_a_fresh_load(resume, listing):
    # Force NEEDS_REVIEW by appending an always-blank required field so the
    # adapter does not click submit. Then we can read back all the values it
    # filled before the confirmation DOM replaces them.
    blocked_fixture_text = FIXTURE_PATH.read_text().replace(
        '<button id="submit_app"',
        '<label for="blocker">Blocker *</label>'
        '<input id="blocker" name="blocker" required>'
        '<button id="submit_app"',
    )
    tmp_fixture = resume.parent / "blocked.html"
    tmp_fixture.write_text(blocked_fixture_text)
    blocked = Listing(
        company=listing.company,
        role=listing.role,
        location=listing.location,
        apply_url=tmp_fixture.as_uri(),
        source=listing.source,
    )
    profile = _make_profile(resume, portfolio="https://jane.dev")

    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, blocked, profile)

        assert result.status is ApplyStatus.NEEDS_REVIEW
        assert page.locator("#first_name").input_value() == "Jane"
        assert page.locator("#last_name").input_value() == "Middle Smith"
        assert page.locator("#email").input_value() == "jane@example.com"
        assert page.locator("#phone").input_value() == "+1 555 555 5555"
        assert page.locator("#q_linkedin").input_value() == "https://linkedin.com/in/jane"
        assert page.locator("#q_github").input_value() == "https://github.com/jane"
        assert page.locator("#q_portfolio").input_value() == "https://jane.dev"


def test_apply_returns_needs_review_when_required_field_blank(resume, listing, tmp_path):
    # Profile with an empty email should leave the required email field blank.
    profile = Profile(
        full_name="Jane Smith",
        email="jane@example.com",
        phone="",
        resume_path=resume,
        linkedin_url="https://linkedin.com/in/jane",
        github_url="https://github.com/jane",
        school="State U",
        degree="BS",
        major="CS",
        graduation_date="2026-05",
        work_authorized_us=True,
        requires_sponsorship=False,
    )
    # Use a modified fixture that has an extra required field the profile
    # can't fill.
    bad_fixture = tmp_path / "greenhouse_bad.html"
    bad_fixture.write_text(FIXTURE_PATH.read_text().replace(
        '<input id="q_github" name="question_1002">',
        '<input id="q_work_auth" name="question_wa" required placeholder="Work auth proof">',
    ))
    bad_listing = Listing(
        company="Acme",
        role="Software Engineer I",
        location="Remote",
        apply_url=bad_fixture.as_uri(),
        source="test",
    )
    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, bad_listing, profile)

    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert result.unfilled_fields, "expected at least one unfilled field name"


def _write_fixture_with_extra_field(tmp_path: Path, extra_html: str) -> Path:
    """Copy the baseline fixture and inject extra HTML just before the submit button."""
    text = FIXTURE_PATH.read_text().replace(
        '<button id="submit_app"',
        extra_html + '<button id="submit_app"',
    )
    out = tmp_path / "with_extra.html"
    out.write_text(text)
    return out


def test_aria_required_field_without_required_attr_is_detected(resume, tmp_path):
    # Greenhouse custom widgets often set aria-required='true' on a control
    # that has no HTML required attribute. Leaving such a field blank must
    # prevent submit.
    fixture = _write_fixture_with_extra_field(
        tmp_path,
        '<label for="q_aria">Custom Q *</label>'
        '<input id="q_aria" name="custom_q" aria-required="true">',
    )
    listing = Listing(
        company="Acme", role="Software Engineer I", location="NYC",
        apply_url=fixture.as_uri(), source="test",
    )
    profile = _make_profile(resume, portfolio="https://jane.dev")

    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert "q_aria" in result.unfilled_fields or "custom_q" in result.unfilled_fields


def test_required_select_with_placeholder_option_is_detected(resume, tmp_path):
    # A select whose selected option is 'Please select' (even with a
    # non-empty value attr) must register as unfilled.
    fixture = _write_fixture_with_extra_field(
        tmp_path,
        '<label for="q_authz">Work Authorization *</label>'
        '<select id="q_authz" name="work_authz" required>'
        '  <option value="0">Please select</option>'
        '  <option value="yes">Yes</option>'
        '  <option value="no">No</option>'
        '</select>',
    )
    listing = Listing(
        company="Acme", role="Software Engineer I", location="NYC",
        apply_url=fixture.as_uri(), source="test",
    )
    profile = _make_profile(resume, portfolio="https://jane.dev")

    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert "q_authz" in result.unfilled_fields or "work_authz" in result.unfilled_fields


def test_label_ending_in_asterisk_is_detected_even_without_required_attr(resume, tmp_path):
    # Legacy forms sometimes render the asterisk as part of the <label> text
    # with no required attribute on the control. The guard walks labels to
    # catch these.
    fixture = _write_fixture_with_extra_field(
        tmp_path,
        '<label for="q_legacy">Legacy Required *</label>'
        '<input id="q_legacy" name="legacy">',
    )
    listing = Listing(
        company="Acme", role="Software Engineer I", location="NYC",
        apply_url=fixture.as_uri(), source="test",
    )
    profile = _make_profile(resume, portfolio="https://jane.dev")

    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert "q_legacy" in result.unfilled_fields


def test_required_select_with_filled_non_placeholder_option_passes(resume, tmp_path):
    # Control case: a required select with a real non-placeholder option
    # selected should not trigger NEEDS_REVIEW.
    fixture = _write_fixture_with_extra_field(
        tmp_path,
        '<label for="q_country">Country *</label>'
        '<select id="q_country" name="country" required>'
        '  <option value="US" selected>United States</option>'
        '  <option value="CA">Canada</option>'
        '</select>',
    )
    listing = Listing(
        company="Acme", role="Software Engineer I", location="NYC",
        apply_url=fixture.as_uri(), source="test",
    )
    profile = _make_profile(resume, portfolio="https://jane.dev")

    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)

    assert result.status is ApplyStatus.SUCCESS, result.message


def test_apply_fails_when_page_does_not_load(resume, tmp_path):
    profile = _make_profile(resume)
    # Point at a fixture that doesn't exist.
    missing = tmp_path / "nonexistent.html"
    listing = Listing(
        company="Nowhere",
        role="Software Engineer I",
        location="NYC",
        apply_url=missing.as_uri(),
        source="test",
    )
    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)
    # file:// load of a missing file renders an error page but does not raise.
    # The form won't be findable, so the adapter should bail at submit lookup.
    assert result.status in (ApplyStatus.FAILED, ApplyStatus.NEEDS_REVIEW)


@pytest.mark.skipif(
    os.environ.get("AAO_RUN_LIVE_TESTS") != "1"
    or not os.environ.get("AAO_LIVE_GREENHOUSE_URL"),
    reason="Live integration test. Set AAO_RUN_LIVE_TESTS=1 and "
           "AAO_LIVE_GREENHOUSE_URL to a real Greenhouse job URL.",
)
def test_live_greenhouse_detects_form(resume):
    """Verify the adapter identifies all core fields on a real Greenhouse job.

    To avoid submitting a real application, we use a profile missing
    LinkedIn, which Greenhouse commonly marks required. The adapter
    should return NEEDS_REVIEW rather than click submit.
    """
    url = os.environ["AAO_LIVE_GREENHOUSE_URL"]
    profile = Profile(
        full_name="Test Applicant",
        email="never-sent@example.invalid",
        phone="+1 555 000 0000",
        resume_path=resume,
        linkedin_url="",  # forces a required LinkedIn field to stay blank
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
    adapter = GreenhouseAdapter()
    with browser_harness(headless=True) as ctx:
        page = ctx.new_page()
        result = adapter.apply(page, listing, profile)
    # We cannot submit to a real company. The test passes if the adapter
    # refused to click submit because something required was blank.
    assert result.status is ApplyStatus.NEEDS_REVIEW, (
        f"expected NEEDS_REVIEW on a real live form with an empty LinkedIn "
        f"field, got {result.status.value}: {result.message}"
    )
