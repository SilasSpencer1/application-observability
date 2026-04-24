from pathlib import Path
import pytest
import yaml

from sync.autoapply.config import load_profile


def _complete_profile_data(resume: Path, **overrides) -> dict:
    data = {
        "full_name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "+1 555 123 4567",
        "resume_path": str(resume),
        "linkedin_url": "https://www.linkedin.com/in/jane",
        "github_url": "https://github.com/jane",
        "portfolio_url": None,
        "school": "State University",
        "degree": "BS",
        "major": "CS",
        "graduation_date": "2026-05",
        "work_authorized_us": True,
        "requires_sponsorship": False,
    }
    data.update(overrides)
    return data


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_valid_profile(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_text("fake pdf")
    profile_path = _write(tmp_path / "profile.yaml", _complete_profile_data(resume))

    profile = load_profile(profile_path)

    assert profile.full_name == "Jane Smith"
    assert profile.email == "jane@example.com"
    assert profile.resume_path == resume
    assert profile.graduation_date == "2026-05"
    assert profile.work_authorized_us is True
    assert profile.requires_sponsorship is False
    assert profile.portfolio_url is None
    assert profile.gender == "decline"
    assert profile.veteran_status == "decline"


def test_missing_required_field_raises(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_text("fake")
    data = _complete_profile_data(resume)
    del data["email"]
    profile_path = _write(tmp_path / "profile.yaml", data)

    with pytest.raises(ValueError, match="email"):
        load_profile(profile_path)


def test_bad_email_raises(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_text("fake")
    profile_path = _write(tmp_path / "profile.yaml", _complete_profile_data(resume, email="not-an-email"))

    with pytest.raises(ValueError, match="email"):
        load_profile(profile_path)


def test_resume_must_exist(tmp_path):
    nonexistent = tmp_path / "resume.pdf"
    profile_path = _write(tmp_path / "profile.yaml", _complete_profile_data(nonexistent))

    with pytest.raises(ValueError, match="resume_path"):
        load_profile(profile_path)


def test_resume_must_be_pdf_or_docx(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("not a pdf")
    profile_path = _write(tmp_path / "profile.yaml", _complete_profile_data(resume))

    with pytest.raises(ValueError, match="PDF or DOCX"):
        load_profile(profile_path)


def test_docx_resume_is_accepted(tmp_path):
    resume = tmp_path / "resume.docx"
    resume.write_text("fake docx")
    profile_path = _write(tmp_path / "profile.yaml", _complete_profile_data(resume))

    profile = load_profile(profile_path)
    assert profile.resume_path == resume


def test_missing_file_raises_filenotfounderror(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nonexistent.yaml")


def test_resume_path_expands_tilde(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    resume = home / "resume.pdf"
    resume.write_text("fake")
    monkeypatch.setenv("HOME", str(home))

    profile_path = _write(
        tmp_path / "profile.yaml",
        _complete_profile_data(resume, resume_path="~/resume.pdf"),
    )
    profile = load_profile(profile_path)
    assert profile.resume_path == resume


def test_eeoc_defaults_when_omitted(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_text("fake")
    data = _complete_profile_data(resume)
    for field in ("gender", "race_ethnicity", "veteran_status", "disability_status", "pronouns"):
        data.pop(field, None)
    profile_path = _write(tmp_path / "profile.yaml", data)

    profile = load_profile(profile_path)
    assert profile.gender == "decline"
    assert profile.race_ethnicity == "decline"
    assert profile.veteran_status == "decline"
    assert profile.disability_status == "decline"
    assert profile.pronouns is None


def test_non_mapping_yaml_raises(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("- just a list\n- of things")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_profile(profile_path)
