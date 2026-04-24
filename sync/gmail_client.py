from __future__ import annotations
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

DEFAULT_HOME = Path.home() / ".application-observability"
DEFAULT_TOKEN_PATH = DEFAULT_HOME / "gmail_token.json"

log = logging.getLogger(__name__)


@dataclass
class GmailMessage:
    message_id: str
    subject: str
    from_name: str
    from_address: str
    body: str
    received_at: str


def _normalize_received_at(raw: str | None) -> str:
    """Parse an RFC 2822 Date header and return canonical UTC ISO form."""
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_body(body: dict | None) -> str:
    data = (body or {}).get("data")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")


def _find_body(payload: dict, target_mime: str) -> str:
    """Depth-first search for a body with the given mime prefix (e.g. text/plain)."""
    mime_type = payload.get("mimeType", "")
    if mime_type.startswith(target_mime):
        decoded = _decode_body(payload.get("body"))
        if decoded:
            return decoded
    for part in payload.get("parts") or []:
        found = _find_body(part, target_mime)
        if found:
            return found
    return ""


def _collect_plain_text(payload: dict) -> str:
    """Prefer text/plain; fall back to text/html if no plain text is present."""
    plain = _find_body(payload, "text/plain")
    if plain:
        return plain
    return _find_body(payload, "text/html")


def _extract_headers(headers: list[dict]) -> dict[str, str]:
    return {h["name"].lower(): h.get("value", "") for h in headers}


def to_message(raw: dict) -> GmailMessage:
    """Convert a Gmail `users.messages.get` response into a GmailMessage."""
    payload = raw.get("payload", {}) or {}
    headers = _extract_headers(payload.get("headers", []) or [])
    from_header = headers.get("from", "")
    from_name, from_address = parseaddr(from_header)
    subject = headers.get("subject", "") or ""
    body = _collect_plain_text(payload) or raw.get("snippet", "") or ""
    received_at = _normalize_received_at(headers.get("date"))
    return GmailMessage(
        message_id=raw.get("id", ""),
        subject=subject,
        from_name=from_name or "",
        from_address=from_address or "",
        body=body,
        received_at=received_at,
    )


class GmailClient:
    """Thin wrapper around the Gmail API for the gmail.readonly scope."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path = DEFAULT_TOKEN_PATH,
    ):
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self._service = None

    def _load_creds(self) -> Credentials:
        creds: Credentials | None = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            self.token_path.write_text(creds.to_json())
        return creds

    def _build_service(self):
        if self._service is None:
            creds = self._load_creds()
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def fetch_messages_since(self, since_iso: str | None):
        """Yield GmailMessage rows received at or after `since_iso` (UTC ISO 8601).

        If since_iso is None, fetches all messages in the inbox up to a safety cap.
        Stops after 5000 messages.
        """
        service = self._build_service()
        query = None
        if since_iso:
            # Gmail search uses seconds since epoch via after:<timestamp>
            dt = datetime.strptime(since_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            query = f"after:{int(dt.timestamp())}"

        page_token = None
        seen = 0
        while seen < 5000:
            req = service.users().messages().list(
                userId="me",
                q=query,
                pageToken=page_token,
                maxResults=100,
            )
            resp = req.execute()
            ids = resp.get("messages", []) or []
            for stub in ids:
                raw = service.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="full",
                ).execute()
                seen += 1
                yield to_message(raw)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
