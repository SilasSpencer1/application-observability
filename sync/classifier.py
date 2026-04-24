from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import yaml

_QUOTED = re.compile(r'"([^"]+)"')

# Job titles often include commas, parentheses, ampersands, apostrophes, dashes
# and slashes. Role names start with a capital letter since formal emails use
# Title Case.
_ROLE_CHARS = r"[A-Za-z0-9 ,\-/()&'.]"

ROLE_PATTERNS = [
    re.compile(rf"\bthe ([A-Z]{_ROLE_CHARS}+?) (?:role|position)"),
    re.compile(rf"received your application for (?:the )?([A-Z]{_ROLE_CHARS}+?)(?:\.|$|\n|\s+(?:role|position|at)\b)"),
    re.compile(rf"apply(?:ing)? for (?:the )?([A-Z]{_ROLE_CHARS}+?)\s+(?:here\s+)?at\b", re.IGNORECASE),
]

# Hints that the text to the right of a dash is a location rather than part of
# the role title. Kept conservative so we don't split things like "Full-stack".
_LOCATION_HINTS = re.compile(
    r"\b(HQ|Office|Remote|Hybrid|Onsite|On-?site|"
    r"San Francisco|New York|NYC|Boston|Seattle|Los Angeles|LA|Chicago|Austin|Denver|"
    r"London|Berlin|Paris|Dublin|Amsterdam|Singapore|Tokyo|Sydney|Toronto|"
    r"United States|USA|US|UK|EU|APAC|EMEA|"
    r"Americas|Europe|Asia)\b",
    re.IGNORECASE,
)
# Matches trailing "- Location" or "(Location)" appended to a role.
_ROLE_LOCATION_TAIL = re.compile(r"\s*[\-–—]\s*([A-Z][^\-–—]+)$|\s*\(([^)]+)\)\s*$")
# "in City, State" or "at our City Office" style picks in the body.
_LOCATION_IN_BODY = re.compile(
    r"\b(?:in|based in|located in|at our)\s+([A-Z][A-Za-z ,]+?)(?:\s+(?:office|HQ))?(?:[.,!?\n]|$)"
)

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
    location: str | None = None

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
        if self._is_ats_sender(email.from_address):
            return "Unknown"
        if "@" in email.from_address:
            domain = email.from_address.split("@", 1)[1]
            host = domain.split(".")[0]
            if host:
                return host.capitalize()
        return "Unknown"

    def extract_role(self, email: Email) -> str | None:
        # Quoted text in subjects is usually the role; in bodies it's often unrelated.
        subject_match = _QUOTED.search(email.subject)
        if subject_match:
            return subject_match.group(1).strip()
        for source in (email.subject, email.body):
            for pat in ROLE_PATTERNS:
                m = pat.search(source)
                if m:
                    return m.group(1).strip()
        return None

    def extract_location(self, email: Email) -> str | None:
        """Pull a location out of the email, either from a trailing tail on the
        role or from common phrasings in the body. Returns None when nothing
        plausible is found."""
        role = self.extract_role(email)
        if role:
            location = _split_location_from_role(role)[1]
            if location:
                return location
        for source in (email.subject, email.body):
            m = _LOCATION_IN_BODY.search(source)
            if m:
                candidate = m.group(1).strip()
                if _LOCATION_HINTS.search(candidate) or "," in candidate:
                    return candidate
        return None

    def classify(self, email: Email) -> Classification | None:
        if not self.passes_job_filter(email):
            return None
        status = self.detect_status(email)
        if status is None:
            return None
        role = self.extract_role(email)
        location = self.extract_location(email)
        if role and location:
            clean_role, tail_location = _split_location_from_role(role)
            if tail_location == location:
                role = clean_role
        return Classification(
            status=status,
            company=self.extract_company(email),
            role=role,
            location=location,
        )


def _split_location_from_role(role: str) -> tuple[str, str | None]:
    """Split a location suffix off the end of a role string when the tail
    contains a location hint. Leaves the role untouched otherwise."""
    m = _ROLE_LOCATION_TAIL.search(role)
    if not m:
        return role, None
    tail = (m.group(1) or m.group(2) or "").strip()
    if not tail or not _LOCATION_HINTS.search(tail):
        return role, None
    return role[: m.start()].rstrip(" -–—"), tail
