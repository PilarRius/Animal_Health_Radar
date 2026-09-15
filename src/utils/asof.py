"""Point-in-time ("as-of") filtering primitives.

This module is the single choke point through which *all* information must
pass before it reaches a feature, a model or a figure.

The rule enforced here
----------------------
    A record may be used for a prediction stamped ``as_of`` if and only if
    ``record.available_from <= as_of``.

``available_from`` is the date at which the fact became knowable to the system
(WAHIS publication, media article publication, ERA5 release, ...) -- *not* the
date the underlying event occurred. A confirmed outbreak with onset on
2024-03-01 that was only published on 2024-04-10 is invisible to any prediction
made before 2024-04-10, which is precisely the gap the Radar is built to model.

Two independent implementations are provided:

``filter_as_of``
    Vectorised, used everywhere in production code.

``filter_as_of_reference``
    Deliberately naive row-by-row version used by the leakage test-suite to
    verify that the fast path has not silently drifted.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from src.utils.dates import DateLike, ensure_timestamp

__all__ = [
    "AVAILABLE_FROM",
    "REFERENCE_DATE",
    "AsOfViolationError",
    "filter_as_of",
    "filter_as_of_reference",
    "latest_as_of",
    "assert_point_in_time",
    "attach_availability",
]

#: Canonical column names used by the point-in-time machinery.
AVAILABLE_FROM = "available_from"
REFERENCE_DATE = "reference_date"


class AsOfViolationError(AssertionError):
    """Raised when a frame contains information published after ``as_of``."""


def _coerce_ts(value: DateLike) -> pd.Timestamp:
    ts = ensure_timestamp(value)
    if ts is None:
        raise ValueError("as_of date must not be null.")
    return ts


def filter_as_of(
    frame: pd.DataFrame,
    as_of: DateLike,
    *,
    available_col: str = AVAILABLE_FROM,
    reference_col: str | None = None,
    max_reference: DateLike | None = None,
    min_reference: DateLike | None = None,
    drop_missing_availability: bool = True,
) -> pd.DataFrame:
    """Return the subset of *frame* knowable at *as_of*.

    Parameters
    ----------
    frame:
        Any long or wide frame carrying an availability column.
    as_of:
        The knowledge cut-off for the prediction being made.
    available_col:
        Column holding the date each row became knowable.
    reference_col, max_reference, min_reference:
        Optional additional restriction on the *event* time axis (for example
        "only reference weeks in the last year").
    drop_missing_availability:
        Rows with a null ``available_from`` cannot be proven to have been
        knowable, so by default they are dropped. Setting this to ``False``
        treats them as always-available and should only be used for static
        reference data (country centroids, disease metadata).

    Returns
    -------
    A copy of the eligible rows (never a view), index reset.
    """
    if available_col not in frame.columns:
        raise KeyError(
            f"Frame has no availability column {available_col!r}; "
            "point-in-time filtering cannot be verified."
        )

    cutoff = _coerce_ts(as_of)
    available = pd.to_datetime(frame[available_col], errors="coerce")

    mask = available <= cutoff
    if not drop_missing_availability:
        mask = mask | available.isna()

    if reference_col is not None:
        if reference_col not in frame.columns:
            raise KeyError(f"Frame has no reference column {reference_col!r}.")
        reference = pd.to_datetime(frame[reference_col], errors="coerce")
        if max_reference is not None:
            mask &= reference <= _coerce_ts(max_reference)
        if min_reference is not None:
            mask &= reference >= _coerce_ts(min_reference)

    return frame.loc[mask.fillna(False)].reset_index(drop=True).copy()


def filter_as_of_reference(
    frame: pd.DataFrame,
    as_of: DateLike,
    *,
    available_col: str = AVAILABLE_FROM,
) -> pd.DataFrame:
    """Naive row-wise reference implementation of :func:`filter_as_of`.

    Used only by :mod:`tests.leakage` as an independent oracle.
    """
    cutoff = _coerce_ts(as_of).date()
    keep: list[int] = []
    for idx, raw in zip(frame.index, frame[available_col], strict=True):
        ts = ensure_timestamp(raw) if not pd.isna(raw) else None
        if ts is not None and ts.date() <= cutoff:
            keep.append(idx)
    return frame.loc[keep].reset_index(drop=True).copy()


def latest_as_of(
    frame: pd.DataFrame,
    *,
    as_of: DateLike,
    keys: Sequence[str],
    available_col: str = AVAILABLE_FROM,
    value_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Latest knowable revision of each key at *as_of*.

    Sources revise their records (WAHIS follow-up reports update case counts).
    This returns, per key, the row with the greatest ``available_from`` not
    exceeding *as_of* -- i.e. the vintage the system would actually have seen.
    """
    eligible = filter_as_of(frame, as_of, available_col=available_col)
    if eligible.empty:
        cols = list(keys) + list(value_cols or [])
        return pd.DataFrame(columns=cols)

    eligible = eligible.sort_values(available_col, kind="mergesort")
    latest = eligible.groupby(list(keys), as_index=False, sort=False).tail(1)
    if value_cols is not None:
        latest = latest[list(keys) + [available_col] + list(value_cols)]
    return latest.reset_index(drop=True)


def assert_point_in_time(
    frame: pd.DataFrame,
    as_of: DateLike,
    *,
    available_col: str = AVAILABLE_FROM,
    context: str = "",
) -> None:
    """Raise :class:`AsOfViolationError` if *frame* leaks post-``as_of`` facts."""
    if available_col not in frame.columns:
        raise AsOfViolationError(
            f"{context or 'frame'}: no {available_col!r} column, point-in-time "
            "correctness cannot be established."
        )
    cutoff = _coerce_ts(as_of)
    available = pd.to_datetime(frame[available_col], errors="coerce")
    offending = int((available > cutoff).sum())
    if offending:
        worst = available.max()
        raise AsOfViolationError(
            f"{context or 'frame'}: {offending} row(s) published after as_of="
            f"{cutoff.date()} (latest={worst}). This is temporal leakage."
        )


def attach_availability(
    frame: pd.DataFrame,
    *,
    base_col: str,
    lag_days: int,
    available_col: str = AVAILABLE_FROM,
    floor: DateLike | None = None,
) -> pd.DataFrame:
    """Stamp an availability date as ``base_col + lag_days``.

    Used for feature families whose publication schedule is a fixed lag behind
    the reference period (ERA5 near-real-time, annual FAOSTAT releases, ...).
    """
    out = frame.copy()
    base = pd.to_datetime(out[base_col], errors="coerce")
    out[available_col] = base + pd.to_timedelta(int(lag_days), unit="D")
    if floor is not None:
        floor_ts = _coerce_ts(floor)
        out[available_col] = out[available_col].clip(lower=floor_ts)
    return out


def as_of_grid(start: DateLike, end: DateLike, step_days: int = 7) -> list[date]:
    """Convenience re-export used by the pre-computation scripts."""
    from src.utils.dates import date_range_days

    return date_range_days(start, end, step=step_days)
