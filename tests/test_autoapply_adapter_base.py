from pathlib import Path
import pytest

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.models import Listing, Profile


def _make_profile(resume: Path) -> Profile:
    return Profile(
        full_name="Jane Smith",
        email="jane@example.com",
        phone="+1 555 555 5555",
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


class _StubAdapter(Adapter):
    name = "stub"

    def __init__(self, result: ApplyResult):
        self._result = result

    def can_handle(self, url: str) -> bool:
        return "stub." in url

    def apply(self, page, listing, profile):
        return self._result


def test_apply_result_defaults():
    r = ApplyResult(status=ApplyStatus.SUCCESS, url="https://x/apply")
    assert r.message is None
    assert r.unfilled_fields == ()


def test_apply_status_serialises_to_string():
    # Backed by str so callers can use .value or compare to literal strings.
    assert ApplyStatus.SUCCESS.value == "success"
    assert ApplyStatus.NEEDS_REVIEW == "needs_review"


def test_adapter_is_abstract_and_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Adapter()  # type: ignore[abstract]


def test_stub_adapter_routes_by_url():
    stub = _StubAdapter(ApplyResult(status=ApplyStatus.SUCCESS, url="https://stub.example/apply"))
    assert stub.can_handle("https://stub.example/apply") is True
    assert stub.can_handle("https://other.example/apply") is False


def test_stub_adapter_returns_result(tmp_path):
    resume = tmp_path / "r.pdf"
    resume.write_text("pdf")
    profile = _make_profile(resume)
    listing = Listing(
        company="Acme",
        role="Software Engineer I",
        location="NYC",
        apply_url="https://stub.example/apply",
    )
    stub = _StubAdapter(ApplyResult(status=ApplyStatus.NEEDS_REVIEW, url=listing.apply_url, unfilled_fields=("phone",)))
    result = stub.apply(page=None, listing=listing, profile=profile)
    assert result.status is ApplyStatus.NEEDS_REVIEW
    assert result.unfilled_fields == ("phone",)
