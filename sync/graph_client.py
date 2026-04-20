from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import sys
import logging

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

DEFAULT_TOKEN_PATH = Path.home() / ".application-observability" / "token.json"

log = logging.getLogger(__name__)


@dataclass
class GraphMessage:
    message_id: str
    subject: str
    from_name: str
    from_address: str
    body: str
    received_at: str


class GraphClient:
    """Thin wrapper around Microsoft Graph for the Mail.Read scope."""

    def __init__(
        self,
        client_id: str,
        token_path: Path = DEFAULT_TOKEN_PATH,
        tenant: str = "common",
    ):
        self.client_id = client_id
        self.token_path = Path(token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = msal.SerializableTokenCache()
        if self.token_path.exists():
            self._cache.deserialize(self.token_path.read_text())
        self._app = msal.PublicClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant}",
            token_cache=self._cache,
        )

    def _persist_cache(self) -> None:
        if self._cache.has_state_changed:
            self.token_path.write_text(self._cache.serialize())

    def acquire_token(self) -> str:
        accounts = self._app.get_accounts()
        result = None
        if accounts:
            result = self._app.acquire_token_silent(SCOPES, account=accounts[0])
        if not result:
            flow = self._app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                raise RuntimeError(f"Device flow failed: {flow}")
            print(flow["message"], file=sys.stderr, flush=True)
            result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Token acquisition failed: {result}")
        self._persist_cache()
        return result["access_token"]
