from pathlib import Path
import pytest

from sync.autoapply.adapters.base import Adapter, ApplyResult, ApplyStatus
from sync.autoapply.adapters.dispatcher import AdapterDispatcher
from sync.autoapply.models import Listing, Profile


class _PatternAdapter(Adapter):
    """Adapter whose can_handle matches a simple URL substring, and whose
    apply returns a configured result or raises a configured exception."""

    def __init__(self, name: str, match: str, result: ApplyResult | None = None,
                 raises: Exception | None = None):
        self.name = name
        self._match = match
        self._result = result
        self._raises = raises
        self.call_count = 0

    def can_handle(self, url: str) -> bool:
        return self._match in url

    def apply(self, page, listing, profile):
        self.call_count += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _listing(url: str) -> Listing:
    return Listing(
        company="C", role="SWE", location=None, apply_url=url, source="test"
    )


def _profile(tmp_path: Path) -> Profile:
    resume = tmp_path / "r.pdf"
    resume.write_bytes(b"%PDF-1.4\n%")
    return Profile(
        full_name="J",
        email="j@e.com",
        phone="1",
        resume_path=resume,
        linkedin_url="https://l",
        github_url="https://g",
        school="S",
        degree="BS",
        major="CS",
        graduation_date="2026-05",
        work_authorized_us=True,
        requires_sponsorship=False,
    )


def test_picks_first_matching_adapter():
    a = _PatternAdapter("a", "ashby")
    b = _PatternAdapter("b", "greenhouse")
    d = AdapterDispatcher([a, b])
    assert d.pick("https://jobs.ashbyhq.com/x") is a
    assert d.pick("https://boards.greenhouse.io/x") is b
    assert d.pick("https://linkedin.com/jobs/x") is None


def test_success_returns_adapter_result_unchanged(tmp_path):
    result = ApplyResult(status=ApplyStatus.SUCCESS, url="https://ashby/x")
    a = _PatternAdapter("a", "ashby", result=result)
    fallback = _PatternAdapter("fb", "", result=ApplyResult(status=ApplyStatus.FAILED, url=""))
    d = AdapterDispatcher([a], fallback=fallback)
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SUCCESS
    assert fallback.call_count == 0


def test_needs_review_triggers_fallback(tmp_path):
    adapter_result = ApplyResult(
        status=ApplyStatus.NEEDS_REVIEW, url="https://ashby/x",
        unfilled_fields=("custom_q",),
    )
    fallback_result = ApplyResult(status=ApplyStatus.SUCCESS, url="https://ashby/x")
    a = _PatternAdapter("a", "ashby", result=adapter_result)
    fallback = _PatternAdapter("fb", "", result=fallback_result)
    d = AdapterDispatcher([a], fallback=fallback)
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SUCCESS
    assert a.call_count == 1
    assert fallback.call_count == 1


def test_failed_triggers_fallback(tmp_path):
    adapter_result = ApplyResult(status=ApplyStatus.FAILED, url="https://ashby/x", message="nope")
    fallback_result = ApplyResult(status=ApplyStatus.SUCCESS, url="https://ashby/x")
    a = _PatternAdapter("a", "ashby", result=adapter_result)
    fallback = _PatternAdapter("fb", "", result=fallback_result)
    d = AdapterDispatcher([a], fallback=fallback)
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SUCCESS


def test_adapter_exception_is_caught_and_fallback_runs(tmp_path):
    fallback_result = ApplyResult(status=ApplyStatus.SUCCESS, url="https://ashby/x")
    a = _PatternAdapter("a", "ashby", raises=RuntimeError("boom"))
    fallback = _PatternAdapter("fb", "", result=fallback_result)
    d = AdapterDispatcher([a], fallback=fallback)
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SUCCESS
    assert fallback.call_count == 1


def test_no_adapter_match_calls_fallback(tmp_path):
    fallback_result = ApplyResult(status=ApplyStatus.SUCCESS, url="https://unknown/x")
    a = _PatternAdapter("a", "greenhouse", result=ApplyResult(status=ApplyStatus.SUCCESS, url=""))
    fallback = _PatternAdapter("fb", "", result=fallback_result)
    d = AdapterDispatcher([a], fallback=fallback)
    out = d.apply(page=None, listing=_listing("https://myworkdayjobs.com/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SUCCESS
    assert a.call_count == 0
    assert fallback.call_count == 1


def test_no_adapter_match_no_fallback_is_skipped(tmp_path):
    a = _PatternAdapter("a", "greenhouse", result=ApplyResult(status=ApplyStatus.SUCCESS, url=""))
    d = AdapterDispatcher([a])
    out = d.apply(page=None, listing=_listing("https://myworkdayjobs.com/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.SKIPPED
    assert a.call_count == 0


def test_adapter_failed_without_fallback_returns_adapter_result(tmp_path):
    adapter_result = ApplyResult(status=ApplyStatus.NEEDS_REVIEW, url="https://ashby/x")
    a = _PatternAdapter("a", "ashby", result=adapter_result)
    d = AdapterDispatcher([a])
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.NEEDS_REVIEW


def test_adapter_exception_without_fallback_returns_failed_result(tmp_path):
    a = _PatternAdapter("a", "ashby", raises=RuntimeError("nope"))
    d = AdapterDispatcher([a])
    out = d.apply(page=None, listing=_listing("https://ashby/x"), profile=_profile(tmp_path))
    assert out.status is ApplyStatus.FAILED
    assert "nope" in (out.message or "")
    assert "a raised" in (out.message or "")
