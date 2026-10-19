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


def test_as_of_period_window_and_clamp():
    p = periods.as_of_period(dt.date(2026, 10, 15), 7)
    assert (p.start, p.end) == (dt.date(2026, 10, 9), dt.date(2026, 10, 16))
    clamped = periods.as_of_period(dt.date(2026, 12, 31), 30, latest=dt.date(2026, 10, 17))
    assert clamped.end == dt.date(2026, 10, 18) and clamped.length_days == 30


def test_resolve_targets_modes():
    from pipeline import runner
    latest = dt.date(2026, 10, 17)
    assert [p.label for p in runner.resolve_targets(latest)] == ["2026-09"]
    assert runner.resolve_targets(latest, months=["2026-01"])[0].label == "2026-01"
    assert runner.resolve_targets(latest, start="2026-10-01", end="2026-10-07")[0].length_days == 7
    as_of = runner.resolve_targets(latest, window_days=10)[0]
    assert as_of.end == dt.date(2026, 10, 18) and as_of.length_days == 10


def test_monthly_anomalies_use_calendar_month_mean():
    from pipeline.timeseries import monthly_anomalies
    series = [(dt.date(2024, 1, 1), 27.0), (dt.date(2024, 2, 1), 28.0),
              (dt.date(2025, 1, 1), 29.0), (dt.date(2025, 2, 1), None)]
    rows = monthly_anomalies(series)
    assert rows[0][2:] == (28.0, -1.0) and rows[2][3] == 1.0
    assert rows[1][3] == 0.0 and rows[3][3] is None
