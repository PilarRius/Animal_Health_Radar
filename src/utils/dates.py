"""Date handling helpers.

The entire system is anchored on two distinct time axes and confusing them is
the classic source of temporal leakage:

``reference_date``
    When something *happened* in the world (onset, week of occurrence).

``available_from`` / ``as_of``
    When a fact *became knowable* to the system (publication, notification).

Every helper here is deliberately timezone-naive and calendar-day based; the
panel resolution is a week starting on Monday.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

__all__ = [
    "ensure_date",
    "ensure_timestamp",
    "iso_week_start",
    "week_starts_between",
    "date_range_days",
    "days_between",
    "add_days",
    "week_of_year",
    "seasonal_harmonics",
    "to_period_start",
]

DateLike = date | datetime | str | pd.Timestamp | np.datetime64


def ensure_date(value: DateLike | None) -> date | None:
    """Coerce anything date-ish to a plain :class:`datetime.date` (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, np.datetime64):
        ts = pd.Timestamp(value)
        return None if pd.isna(ts) else ts.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "nat", "none", "null"}:
            return None
        return pd.Timestamp(text).date()
    if isinstance(value, float) and np.isnan(value):
        return None
    raise TypeError(f"Cannot interpret {value!r} ({type(value)}) as a date.")


def ensure_timestamp(value: DateLike | None) -> pd.Timestamp | None:
    """Coerce to a normalized (midnight) :class:`pandas.Timestamp`."""
    resolved = ensure_date(value)
    return None if resolved is None else pd.Timestamp(resolved)


def iso_week_start(value: DateLike) -> date:
    """Return the Monday of the week containing *value*."""
    resolved = ensure_date(value)
    if resolved is None:
        raise ValueError("iso_week_start requires a non-null date.")
    return resolved - timedelta(days=resolved.weekday())


def to_period_start(value: DateLike, freq: str = "W-MON") -> date:
    """Snap a date to the start of its panel period.

    Only weekly (``W-MON``) and monthly (``MS``) frequencies are used here.
    """
    resolved = ensure_date(value)
    if resolved is None:
        raise ValueError("to_period_start requires a non-null date.")
    if freq.upper().startswith("W"):
        return iso_week_start(resolved)
    if freq.upper() in {"MS", "M"}:
        return resolved.replace(day=1)
    if freq.upper() in {"D"}:
        return resolved
    raise ValueError(f"Unsupported panel frequency: {freq!r}")


def week_starts_between(start: DateLike, end: DateLike) -> list[date]:
    """All Mondays in ``[start, end]`` (inclusive of the week containing *start*)."""
    first = iso_week_start(start)
    last = iso_week_start(end)
    out: list[date] = []
    cursor = first
    while cursor <= last:
        out.append(cursor)
        cursor += timedelta(days=7)
    return out


def date_range_days(start: DateLike, end: DateLike, step: int = 1) -> list[date]:
    """Inclusive list of dates from *start* to *end* stepping *step* days."""
    first = ensure_date(start)
    last = ensure_date(end)
    if first is None or last is None:
        raise ValueError("date_range_days requires non-null bounds.")
    if step <= 0:
        raise ValueError("step must be a positive number of days.")
    out: list[date] = []
    cursor = first
    while cursor <= last:
        out.append(cursor)
        cursor += timedelta(days=step)
    return out


def days_between(later: DateLike, earlier: DateLike) -> int | None:
    """``later - earlier`` in whole days, or ``None`` if either side is missing."""
    a = ensure_date(later)
    b = ensure_date(earlier)
    if a is None or b is None:
        return None
    return (a - b).days


def add_days(value: DateLike, days: int) -> date:
    resolved = ensure_date(value)
    if resolved is None:
        raise ValueError("add_days requires a non-null date.")
    return resolved + timedelta(days=int(days))


def week_of_year(value: DateLike) -> int:
    """ISO week number (1-53)."""
    resolved = ensure_date(value)
    if resolved is None:
        raise ValueError("week_of_year requires a non-null date.")
    return int(resolved.isocalendar().week)


def seasonal_harmonics(
    values: Iterable[DateLike], n_harmonics: int = 2, period_weeks: float = 52.18
) -> pd.DataFrame:
    """Fourier seasonality terms for a sequence of dates.

    Returns a frame with columns ``sin_1, cos_1, ... sin_k, cos_k``. Harmonic
    regression is used instead of week-of-year dummies to keep the number of
    forecast-model parameters small on short series.
    """
    weeks = np.array(
        [((ensure_date(v) - date(2020, 1, 6)).days / 7.0) for v in values],  # type: ignore[operator]
        dtype=float,
    )
    data: dict[str, np.ndarray] = {}
    for k in range(1, n_harmonics + 1):
        angle = 2.0 * np.pi * k * weeks / period_weeks
        data[f"sin_{k}"] = np.sin(angle)
        data[f"cos_{k}"] = np.cos(angle)
    return pd.DataFrame(data)


def iter_weeks(start: DateLike, end: DateLike) -> Iterator[date]:
    """Lazy variant of :func:`week_starts_between`."""
    cursor = iso_week_start(start)
    last = iso_week_start(end)
    while cursor <= last:
        yield cursor
        cursor += timedelta(days=7)
