from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Listing:
    """A single job posting pulled from a listing source.

    apply_url is the direct ATS link (Greenhouse / Ashby / Workday / etc.).
    simplify_url, when present, is the branded simplify.jobs/p/<id> redirect
    used by the Simplify extension fallback.
    """
    company: str
    role: str
    location: str | None
    apply_url: str
    simplify_url: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class Profile:
    """User data an ATS adapter fills into an application form.

    Loaded from ~/.application-observability/profile.yaml. EEOC fields
    default to 'decline' so we never submit an inferred answer the user
    did not explicitly set.
    """
    full_name: str
    email: str
    phone: str
    resume_path: Path

    linkedin_url: str
    github_url: str

    school: str
    degree: str
    major: str
    graduation_date: str  # YYYY-MM

    work_authorized_us: bool
    requires_sponsorship: bool

    portfolio_url: str | None = None
    pronouns: str | None = None

    gender: str = "decline"
    race_ethnicity: str = "decline"
    veteran_status: str = "decline"
    disability_status: str = "decline"

    def validate(self) -> None:
        if not self.full_name.strip():
            raise ValueError("full_name is required")
        if "@" not in self.email or "." not in self.email.split("@", 1)[1]:
            raise ValueError(f"email does not look like an email: {self.email!r}")
        if not self.resume_path.exists():
            raise ValueError(f"resume_path does not exist: {self.resume_path}")
        if self.resume_path.suffix.lower() not in {".pdf", ".docx"}:
            raise ValueError(f"resume_path must be a PDF or DOCX file: {self.resume_path}")
