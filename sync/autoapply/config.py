from __future__ import annotations
from pathlib import Path
import yaml

from sync.autoapply.models import Profile

DEFAULT_PROFILE_PATH = Path.home() / ".application-observability" / "profile.yaml"

_REQUIRED_FIELDS = (
    "full_name",
    "email",
    "phone",
    "resume_path",
    "linkedin_url",
    "github_url",
    "school",
    "degree",
    "major",
    "graduation_date",
    "work_authorized_us",
    "requires_sponsorship",
)


def load_profile(path: Path | None = None) -> Profile:
    """Load and validate a Profile from YAML.

    Raises FileNotFoundError if the profile file is missing, and ValueError
    for malformed YAML, missing required fields, or failed validation.
    """
    profile_path = path or DEFAULT_PROFILE_PATH
    if not profile_path.exists():
        raise FileNotFoundError(
            f"profile.yaml not found at {profile_path}. "
            f"Copy profile.example.yaml to that location and fill it in."
        )

    data = yaml.safe_load(profile_path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"profile YAML must be a mapping, got {type(data).__name__}")

    missing = [
        f for f in _REQUIRED_FIELDS
        if f not in data
        or data[f] is None
        or (isinstance(data[f], str) and not data[f].strip())
    ]
    if missing:
        raise ValueError(f"profile.yaml missing required field(s): {', '.join(missing)}")

    profile = Profile(
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        resume_path=Path(data["resume_path"]).expanduser(),
        linkedin_url=data["linkedin_url"],
        github_url=data["github_url"],
        school=data["school"],
        degree=data["degree"],
        major=data["major"],
        graduation_date=data["graduation_date"],
        work_authorized_us=bool(data["work_authorized_us"]),
        requires_sponsorship=bool(data["requires_sponsorship"]),
        portfolio_url=data.get("portfolio_url"),
        pronouns=data.get("pronouns"),
        gender=data.get("gender") or "decline",
        race_ethnicity=data.get("race_ethnicity") or "decline",
        veteran_status=data.get("veteran_status") or "decline",
        disability_status=data.get("disability_status") or "decline",
    )
    profile.validate()
    return profile
