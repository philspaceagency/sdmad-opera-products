"""Date-range helpers (pure Python, no Earth Engine dependency)."""

import calendar
import datetime as dt
from dataclasses import dataclass

ONE_DAY = dt.timedelta(days=1)


@dataclass(frozen=True)
class Period:
    start: dt.date  # inclusive
    end: dt.date    # exclusive

    @property
    def last(self) -> dt.date:
        return self.end - ONE_DAY

    @property
    def label(self) -> str:
        if self.is_calendar_month:
            return self.start.strftime("%Y-%m")
        if self.last == self.start:
            return self.start.strftime("%Y%m%d")
        return f"{self.start:%Y%m%d}_{self.last:%Y%m%d}"

    @property
    def is_calendar_month(self) -> bool:
        return self.start.day == 1 and self == month_period(self.start.year, self.start.month)

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


def time_range(start, end) -> Period:
    """Inclusive start/end (ISO strings or dates) -> Period with exclusive end."""
    s = start if isinstance(start, dt.date) else dt.date.fromisoformat(start)
    e = end if isinstance(end, dt.date) else dt.date.fromisoformat(end)
    if e < s:
        raise ValueError(f"end {e} is before start {s}")
    return Period(s, e + ONE_DAY)


def split_by_month(period: Period) -> list:
    """2026-09-20..2026-10-15 -> [2026-09-20..09-30, 2026-10-01..10-15]."""
    chunks, cur = [], period.start
    while cur < period.end:
        month = month_period(cur.year, cur.month)
        chunks.append(Period(cur, min(month.end, period.end)))
        cur = month.end
    return chunks


def days(period: Period) -> list:
    return [period.start + dt.timedelta(days=i) for i in range(period.length_days)]


def centered_window(day: dt.date, half_width: int) -> Period:
    """`day` +/- `half_width` days (used for the daily climatology)."""
    return Period(day - dt.timedelta(days=half_width), day + dt.timedelta(days=half_width + 1))


def union(a: Period, b: Period) -> Period:
    """Smallest period covering both."""
    if a is None:
        return b
    return Period(min(a.start, b.start), max(a.end, b.end))


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
