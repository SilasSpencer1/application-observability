import pytest

from sync.autoapply.filter import is_entry_level, filter_entry_level
from sync.autoapply.models import Listing


@pytest.mark.parametrize(
    "role",
    [
        "Software Engineer I",
        "Software Engineer 1",
        "Software Engineer, New Grad",
        "Software Engineer – New Grad",
        "New Grad Software Engineer",
        "Junior Software Engineer",
        "Associate Software Engineer",
        "Early Career Software Engineer",
        "Entry Level Software Engineer",
        "Software Engineer, Level I",
        "Product Engineer 1 - Hoods & Fenders",
        "Software Engineer",
    ],
)
def test_entry_level_roles_pass(role):
    assert is_entry_level(role) is True, f"expected {role!r} to pass"


@pytest.mark.parametrize(
    "role",
    [
        "Senior Software Engineer",
        "Sr. Software Engineer",
        "Sr Software Engineer",
        "Staff Software Engineer",
        "Principal Engineer",
        "Tech Lead",
        "Engineering Manager",
        "Director of Engineering",
        "VP of Engineering",
        "Head of Platform",
        "Software Engineer II",
        "Software Engineer III",
        "Software Engineer IV",
        "Software Engineer, L3",
        "Software Engineer Intern",
        "Software Engineering Internship",
    ],
)
def test_senior_or_intern_roles_are_blocked(role):
    assert is_entry_level(role) is False, f"expected {role!r} to be blocked"


def test_filter_entry_level_yields_only_passing_listings():
    inputs = [
        Listing("Stripe", "Software Engineer I", None, "https://x/1"),
        Listing("Stripe", "Senior Engineer", None, "https://x/2"),
        Listing("Notion", "Software Engineer, New Grad", None, "https://x/3"),
        Listing("Acme", "Engineering Manager", None, "https://x/4"),
    ]
    kept = list(filter_entry_level(inputs))
    assert [l.role for l in kept] == [
        "Software Engineer I",
        "Software Engineer, New Grad",
    ]


def test_leadership_program_is_not_blocked_by_lead_pattern():
    # Word-boundary check: 'Leadership' does not trigger \blead\b.
    assert is_entry_level("Software Engineer – Leadership Program") is True


def test_single_roman_numeral_i_is_not_blocked():
    # \b(II|III|IV|V)\b must not match a solitary 'I'.
    assert is_entry_level("Software Engineer I") is True
