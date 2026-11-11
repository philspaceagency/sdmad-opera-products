import datetime as dt

import pytest

from pipeline import periods


def test_parse_month_handles_leap_february():
    p = periods.parse_month("2024-02")
    assert (p.start, p.end) == (dt.date(2024, 2, 1), dt.date(2024, 3, 1))
    assert p.is_calendar_month and p.label == "2024-02"


def test_time_range_end_is_inclusive():
    p = periods.time_range("2026-10-01", "2026-10-07")
    assert p.end == dt.date(2026, 10, 8) and p.length_days == 7 and p.last == dt.date(2026, 10, 7)
    assert p.label == "20261001_20261007"
    assert periods.time_range("2026-10-01", "2026-10-01").label == "20261001"
    with pytest.raises(ValueError):
        periods.time_range("2026-10-07", "2026-10-01")


def test_split_by_month():
    chunks = periods.split_by_month(periods.time_range("2026-09-20", "2026-11-03"))
    assert [(c.start.isoformat(), c.last.isoformat()) for c in chunks] == [
        ("2026-09-20", "2026-09-30"), ("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-03")]
    assert chunks[1].is_calendar_month


def test_days_window_and_union():
    p = periods.time_range("2026-02-27", "2026-03-02")
    assert periods.days(p) == [dt.date(2026, 2, 27), dt.date(2026, 2, 28), dt.date(2026, 3, 1), dt.date(2026, 3, 2)]
    w = periods.centered_window(dt.date(2026, 1, 3), 7)
    assert (w.start, w.last, w.length_days) == (dt.date(2025, 12, 27), dt.date(2026, 1, 10), 15)
    a, b = periods.time_range("2026-10-01", "2026-10-15"), periods.time_range("2026-10-10", "2026-10-31")
    assert periods.union(a, b) == periods.parse_month("2026-10") and periods.union(None, a) == a


def test_monthly_anomalies_use_calendar_month_mean():
    from pipeline.timeseries import monthly_anomalies
    series = [(dt.date(2024, 1, 1), 27.0), (dt.date(2024, 2, 1), 28.0),
              (dt.date(2025, 1, 1), 29.0), (dt.date(2025, 2, 1), None)]
    rows = monthly_anomalies(series)
    assert rows[0][2:] == (28.0, -1.0) and rows[2][3] == 1.0
    assert rows[1][3] == 0.0 and rows[3][3] is None
