from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import yaml

ROLE_PATTERNS = [
    re.compile(r'"([^"]+)"'),                                                 # quoted phrase
    re.compile(r"\bthe ([A-Z][\w \-/]+?) (?:role|position)"),                 # "...the X role/position..."
    re.compile(r"received your application for (?:the )?([A-Z][\w \-/]+?)(?:\.|$|\n|\s+(?:role|position|at)\b)"),
]

@dataclass(frozen=True)
class Email:
    message_id: str
    subject: str
    from_name: str
    from_address: str
    body: str
    received_at: str  # ISO 8601 string from Graph

@dataclass(frozen=True)
class Classification:
    status: str | None
    company: str | None
    role: str | None

class Classifier:
    def __init__(self, rules: dict):
        self._rules = rules
        self._job_filter = [k.lower() for k in rules["job_filter"]]

    @classmethod
    def from_yaml(cls, path: Path) -> "Classifier":
        return cls(yaml.safe_load(path.read_text()))

    def passes_job_filter(self, email: Email) -> bool:
        haystack = f"{email.subject}\n{email.body}".lower()
        return any(kw in haystack for kw in self._job_filter)

    def detect_status(self, email: Email) -> str | None:
        haystack = f"{email.subject}\n{email.body}".lower()
        for status in self._rules["status_order"]:
            patterns = [p.lower() for p in self._rules["status_patterns"][status]]
            if any(p in haystack for p in patterns):
                return status
        return None

    def _is_ats_sender(self, address: str) -> bool:
        addr = address.lower()
        for domains in self._rules["ats_senders"].values():
            if any(addr.endswith("@" + d) or addr.endswith("." + d) for d in domains):
                return True
        return False

    def _strip_company_suffixes(self, name: str) -> str:
        result = name
        for suffix in self._rules["company_suffix_strip"]:
            lower_suffix = suffix.lower()
            if result.lower().endswith(lower_suffix):
                result = result[: -len(lower_suffix)]
        return result.strip(" -|·")

    def extract_company(self, email: Email) -> str:
        if email.from_name:
            cleaned = self._strip_company_suffixes(email.from_name)
            if cleaned:
                return cleaned
        if "@" in email.from_address:
            domain = email.from_address.split("@", 1)[1]
            host = domain.split(".")[0]
            if host:
                return host.capitalize()
        return "Unknown"

    def extract_role(self, email: Email) -> str | None:
        for source in (email.subject, email.body):
            for pat in ROLE_PATTERNS:
                m = pat.search(source)
                if m:
                    return m.group(1).strip()
        return None
