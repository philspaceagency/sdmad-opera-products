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
