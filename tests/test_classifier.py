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
