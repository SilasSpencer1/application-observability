import base64
import pytest
from sync.gmail_client import to_message, _normalize_received_at


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


@pytest.mark.parametrize("raw,expected", [
    ("Mon, 01 Mar 2026 10:00:00 +0000", "2026-03-01T10:00:00Z"),
    ("Mon, 01 Mar 2026 05:00:00 -0500", "2026-03-01T10:00:00Z"),
    ("", ""),
    ("not-a-date", ""),
])
def test_normalize_received_at(raw, expected):
    assert _normalize_received_at(raw) == expected


def test_to_message_extracts_headers_and_plain_text():
    raw = {
        "id": "gm-123",
        "snippet": "Thank you for applying to Stripe",
        "payload": {
            "headers": [
                {"name": "From", "value": "Stripe Recruiting <no-reply@greenhouse.io>"},
                {"name": "Subject", "value": "Thank you for applying to Stripe"},
                {"name": "Date", "value": "Mon, 01 Mar 2026 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Hi Silas, thank you for applying to the Software Engineer role at Stripe.")},
        },
    }
    msg = to_message(raw)
    assert msg.message_id == "gm-123"
    assert msg.subject == "Thank you for applying to Stripe"
    assert msg.from_name == "Stripe Recruiting"
    assert msg.from_address == "no-reply@greenhouse.io"
    assert "Software Engineer" in msg.body
    assert msg.received_at == "2026-03-01T10:00:00Z"


def test_to_message_walks_multipart_for_plain_text():
    raw = {
        "id": "gm-456",
        "payload": {
            "headers": [
                {"name": "From", "value": "careers@acme.com"},
                {"name": "Subject", "value": "Application received"},
                {"name": "Date", "value": "Tue, 02 Mar 2026 10:00:00 +0000"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>Ignored HTML</p>")},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Plain text body for Backend Engineer application")},
                },
            ],
        },
    }
    msg = to_message(raw)
    assert msg.from_name == ""
    assert msg.from_address == "careers@acme.com"
    assert msg.body.startswith("Plain text body")


def test_to_message_falls_back_to_snippet_when_no_body():
    raw = {
        "id": "gm-789",
        "snippet": "snippet body",
        "payload": {
            "headers": [
                {"name": "From", "value": "x@example.com"},
                {"name": "Subject", "value": "s"},
                {"name": "Date", "value": "Wed, 03 Mar 2026 10:00:00 +0000"},
            ],
        },
    }
    msg = to_message(raw)
    assert msg.body == "snippet body"
