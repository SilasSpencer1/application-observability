from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

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
