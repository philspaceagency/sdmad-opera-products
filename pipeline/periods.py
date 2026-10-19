"""Target-period helpers (pure Python, no Earth Engine dependency)."""

import calendar
import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Period:
    start: dt.date  # inclusive
    end: dt.date    # exclusive

    @property
    def label(self) -> str:
        if self.is_calendar_month:
            return self.start.strftime("%Y-%m")
        last = self.end - dt.timedelta(days=1)
        if last == self.start:
            return self.start.strftime("%Y%m%d")
        return f"{self.start:%Y%m%d}_{last:%Y%m%d}"

    @property
    def is_calendar_month(self) -> bool:
        if self.start.day != 1:
            return False
        days = calendar.monthrange(self.start.year, self.start.month)[1]
        return self.end == self.start + dt.timedelta(days=days)

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days


def month_period(year: int, month: int) -> Period:
    start = dt.date(year, month, 1)
    days = calendar.monthrange(year, month)[1]
    return Period(start, start + dt.timedelta(days=days))


def parse_month(text: str) -> Period:
    """'2026-09' -> Period(2026-09-01, 2026-10-01)."""
    year, month = (int(x) for x in text.split("-"))
    return month_period(year, month)


def month_range(first: str, last: str) -> list:
    """All calendar months from `first` to `last` inclusive ('YYYY-MM')."""
    start, stop = parse_month(first), parse_month(last)
    if stop.start < start.start:
        raise ValueError(f"{last} is before {first}")
    periods, cur = [], start
    while cur.start <= stop.start:
        periods.append(cur)
        cur = month_period(cur.end.year, cur.end.month)
    return periods


def custom_period(start: str, end: str) -> Period:
    """Inclusive ISO dates -> Period with exclusive end."""
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end) + dt.timedelta(days=1)
    if e <= s:
        raise ValueError("end must be on or after start")
    if (e - s).days > 366:
        raise ValueError("custom periods longer than a year are not supported for anomalies")
    return Period(s, e)


def last_complete_month(latest: dt.date) -> Period:
    """Latest calendar month fully covered by data available up to `latest`."""
    month = month_period(latest.year, latest.month)
    if latest >= month.end - dt.timedelta(days=1):
        return month
    prev = month.start - dt.timedelta(days=1)
    return month_period(prev.year, prev.month)


ONE_DAY = dt.timedelta(days=1)


def month_labels(first: str, last: str) -> list:
    return [p.label for p in month_range(first, last)]


def as_of_period(as_of: dt.date, window_days: int, latest: dt.date = None) -> Period:
    """`window_days` days ending on `as_of` (inclusive), clamped to the latest available date."""
    if window_days < 1 or window_days > 366:
        raise ValueError("window_days must be between 1 and 366")
    if latest is not None and as_of > latest:
        as_of = latest
    end = as_of + ONE_DAY
    return Period(end - dt.timedelta(days=window_days), end)


def shift_years(period: Period, years: int) -> Period:
    """The same calendar window `years` later (earlier if negative). Feb 29 falls back to Feb 28."""
    if period.is_calendar_month:
        return month_period(period.start.year + years, period.start.month)
    year = period.start.year + years
    try:
        start = period.start.replace(year=year)
    except ValueError:
        start = period.start.replace(year=year, day=28)
    return Period(start, start + dt.timedelta(days=period.length_days))
