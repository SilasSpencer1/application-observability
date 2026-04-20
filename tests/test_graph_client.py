import pytest
from sync.graph_client import normalize_iso_utc

@pytest.mark.parametrize("raw,expected", [
    ("2026-03-01T10:00:00Z", "2026-03-01T10:00:00Z"),
    ("2026-03-01T10:00:00.000Z", "2026-03-01T10:00:00Z"),
    ("2026-03-01T10:00:00.123456Z", "2026-03-01T10:00:00Z"),
    ("2026-03-01T10:00:00+00:00", "2026-03-01T10:00:00Z"),
    ("2026-03-01T05:00:00-05:00", "2026-03-01T10:00:00Z"),
])
def test_normalize_iso_utc_canonicalizes(raw, expected):
    assert normalize_iso_utc(raw) == expected
