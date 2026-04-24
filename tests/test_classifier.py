import json
from pathlib import Path
import pytest
from sync.classifier import Classifier, Email

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_emails.json"

@pytest.fixture(scope="module")
def fixtures():
    return json.loads(FIXTURE_PATH.read_text())

@pytest.fixture(scope="module")
def classifier():
    rules_path = Path(__file__).parent.parent / "sync" / "rules.yaml"
    return Classifier.from_yaml(rules_path)

def email_from_fixture(fx: dict) -> Email:
    return Email(
        message_id=fx["id"],
        subject=fx["subject"],
        from_name=fx["from_name"],
        from_address=fx["from_address"],
        body=fx["body"],
        received_at=fx["received_at"],
    )

def test_job_filter_skips_unrelated_email(classifier, fixtures):
    noise = next(f for f in fixtures if f["id"] == "msg-noise-newsletter")
    assert classifier.passes_job_filter(email_from_fixture(noise)) is False

def test_job_filter_passes_engineering_email(classifier, fixtures):
    applied = next(f for f in fixtures if f["id"] == "msg-applied-greenhouse")
    assert classifier.passes_job_filter(email_from_fixture(applied)) is True

def test_status_detection_for_each_fixture(classifier, fixtures):
    for fx in fixtures:
        email = email_from_fixture(fx)
        if not classifier.passes_job_filter(email):
            assert fx["expected_status"] is None, f"{fx['id']} unexpectedly filtered"
            continue
        assert classifier.detect_status(email) == fx["expected_status"], (
            f"{fx['id']} status mismatch"
        )

def test_company_extraction(classifier, fixtures):
    for fx in fixtures:
        if fx["expected_company"] is None:
            continue
        email = email_from_fixture(fx)
        assert classifier.extract_company(email) == fx["expected_company"], (
            f"{fx['id']} company mismatch"
        )

def test_role_extraction(classifier, fixtures):
    for fx in fixtures:
        if fx["expected_role"] is None:
            continue
        email = email_from_fixture(fx)
        assert classifier.extract_role(email) == fx["expected_role"], (
            f"{fx['id']} role mismatch"
        )

def test_extract_company_returns_unknown_for_ats_sender_without_display_name(classifier):
    email = Email(
        message_id="m-ats",
        subject="Thank you for applying to Software Engineer",
        from_name="",
        from_address="no-reply@us.greenhouse-mail.io",
        body="",
        received_at="2026-03-01T00:00:00Z",
    )
    assert classifier.extract_company(email) == "Unknown"


@pytest.mark.parametrize("from_name,from_address,expected", [
    ("Sift Talent Team", "no-reply@ashbyhq.com", "Sift"),
    ("Crusoe Hiring Team", "no-reply@ashbyhq.com", "Crusoe"),
    ("Nectar Hiring Team", "no-reply@ashbyhq.com", "Nectar"),
    ("do-not-reply adobe", "adobe@myworkday.com", "Adobe"),
    ("Recruiting Team at EliseAI", "no-reply@ashbyhq.com", "EliseAI"),
    ("", "noreply@mail.amazon.jobs", "Amazon"),
    ("", "careers@dataco.co.uk", "Dataco"),
    ("nue.io", "hello@nue.io", "nue.io"),
    # Multi-suffix names collapse in one pass.
    ("Valon Tech Hiring Team", "no-reply@ashbyhq.com", "Valon"),
])
def test_extract_company_cleans_prefixes_suffixes_and_subdomains(classifier, from_name, from_address, expected):
    email = Email(
        message_id="m",
        subject="Thank you for applying",
        from_name=from_name,
        from_address=from_address,
        body="thank you for applying",
        received_at="2026-03-01T00:00:00Z",
    )
    assert classifier.extract_company(email) == expected


@pytest.mark.parametrize("subject,body,expected_status", [
    # Real wording that used to mislabel applied emails as next_step because of
    # phrases like "discuss next steps" in future-tense boilerplate.
    (
        "Thank you for applying to Nectar Social!",
        "Thank you for your interest in the Software Engineer, Early Career role at Nectar Social. "
        "Your application has been received. If your background aligns, we'll reach out to discuss next steps.",
        "applied",
    ),
    # Rejection that contained "no longer interviewing" and used to be read as
    # next_step because "interview" appeared as a substring.
    (
        "Thank You for applying to Sift",
        "Thank you for taking the time to apply for the Software Engineer role at Sift. "
        "Unfortunately we have filled this role and are no longer interviewing.",
        "rejected",
    ),
    # Rejection that used smart quotes ("we’ve decided"). The classifier
    # should collapse typographic punctuation before matching.
    (
        "Application Update",
        "Thank you for expressing interest in the role at Maybern. We’ve decided to move forward with other applicants.",
        "rejected",
    ),
    # Short confirmation email that never names an engineering role. The old
    # filter rejected these outright; the new "apply to" keyword lets them in.
    (
        "Thank you for applying to Loop",
        "Thanks for applying to Loop. Your application has been received and we will review it right away.",
        "applied",
    ),
])
def test_real_email_phrasings_classify_correctly(classifier, subject, body, expected_status):
    email = Email(
        message_id="m",
        subject=subject,
        from_name="",
        from_address="noreply@example.com",
        body=body,
        received_at="2026-03-01T00:00:00Z",
    )
    result = classifier.classify(email)
    assert result is not None, "email unexpectedly skipped by job filter"
    assert result.status == expected_status

def test_classify_full_pipeline(classifier, fixtures):
    for fx in fixtures:
        result = classifier.classify(email_from_fixture(fx))
        if fx["expected_status"] is None:
            assert result is None, f"{fx['id']} should have been skipped, got {result}"
        else:
            assert result is not None, f"{fx['id']} should have classified"
            assert result.status == fx["expected_status"]
            assert result.company == fx["expected_company"]
            assert result.role == fx["expected_role"]
