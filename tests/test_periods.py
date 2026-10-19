import datetime as dt

import pytest

from pipeline import periods


def test_parse_month_handles_leap_february():
    p = periods.parse_month("2024-02")
    assert (p.start, p.end) == (dt.date(2024, 2, 1), dt.date(2024, 3, 1))
    assert p.is_calendar_month and p.label == "2024-02"


def test_month_range_crosses_year():
    labels = [p.label for p in periods.month_range("2025-11", "2026-02")]
    assert labels == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_custom_period_end_is_inclusive():
    p = periods.custom_period("2026-10-01", "2026-10-07")
    assert p.end == dt.date(2026, 10, 8) and p.length_days == 7
    assert p.label == "20261001_20261007"
    assert periods.custom_period("2026-10-01", "2026-10-01").label == "20261001"


def test_custom_period_rejects_bad_ranges():
    with pytest.raises(ValueError):
        periods.custom_period("2026-10-07", "2026-10-01")
    with pytest.raises(ValueError):
        periods.custom_period("2024-01-01", "2025-06-01")


@pytest.mark.parametrize("latest,expected", [
    (dt.date(2026, 10, 17), "2026-09"),
    (dt.date(2026, 9, 30), "2026-09"),
    (dt.date(2026, 1, 5), "2025-12"),
])
def test_last_complete_month(latest, expected):
    assert periods.last_complete_month(latest).label == expected
