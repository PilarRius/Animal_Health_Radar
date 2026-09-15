"""Shared derivations for turning raw source counts into usable signals.

A raw article count is not a probability and must never be handed to a model as
though it were. What carries information is *departure from what is normal for
this country, this disease, at this time of year* -- and how fast that
departure is growing.

All derivations here are strictly **causal**: the statistic at week ``w`` uses
observations up to and including ``w`` only. That property is what allows the
resulting signal to be stamped with an ``available_from`` of ``w + lag`` and
survive the point-in-time audit.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from src.utils.stats import ewma_z_score, safe_log

__all__ = [
    "to_weekly",
    "derive_anomaly_block",
    "expanding_seasonal_baseline",
    "emit_weekly_signals",
]


def to_weekly(
    frame: pd.DataFrame,
    *,
    date_col: str,
    group_cols: Sequence[str],
    agg: dict[str, str],
) -> pd.DataFrame:
    """Aggregate a dated record table onto the Monday-start weekly grid."""
    out = frame.copy()
    dates = pd.to_datetime(out[date_col], errors="coerce")
    out = out.loc[dates.notna()].copy()
    dates = dates.loc[dates.notna()]
    out["week_start"] = (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize()
    grouped = out.groupby([*group_cols, "week_start"], as_index=False).agg(agg)
    return grouped.sort_values([*group_cols, "week_start"]).reset_index(drop=True)


def derive_anomaly_block(
    weekly: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    value_col: str,
    prefix: str,
    alpha: float = 0.30,
    baseline_weeks: int = 8,
) -> pd.DataFrame:
    """Add abnormal-volume, acceleration and baseline-ratio columns.

    Columns added (all causal):

    ``{prefix}_volume``
        ``log1p`` of the raw weekly count -- the level, kept for reference.
    ``{prefix}_abnormal_volume``
        EWMA control-chart z-score of the log volume. Positive means this week
        is louder than the recent norm for this series.
    ``{prefix}_acceleration``
        Second difference of the log volume: is the departure itself growing?
    ``{prefix}_baseline_ratio``
        Volume divided by the trailing median (shifted by one week so the
        current observation never enters its own baseline).
    """
    frame = weekly.sort_values([*group_cols, "week_start"]).copy()
    log_value = safe_log(frame[value_col].to_numpy(dtype=float))
    frame[f"{prefix}_volume"] = log_value

    keys = list(group_cols)
    grouped = frame.groupby(keys, sort=False)

    frame[f"{prefix}_abnormal_volume"] = grouped[f"{prefix}_volume"].transform(
        lambda s: pd.Series(ewma_z_score(s.to_numpy(dtype=float), alpha=alpha), index=s.index)
    )

    first_diff = grouped[f"{prefix}_volume"].diff()
    frame[f"{prefix}_acceleration"] = first_diff.groupby(
        [frame[k] for k in keys], sort=False
    ).diff().fillna(0.0)

    trailing_median = grouped[value_col].transform(
        lambda s: s.shift(1).rolling(baseline_weeks, min_periods=2).median()
    )
    frame[f"{prefix}_baseline_ratio"] = (
        (frame[value_col] + 1.0) / (trailing_median.fillna(frame[value_col].median()) + 1.0)
    ).clip(0.0, 25.0)

    frame[f"{prefix}_abnormal_volume"] = frame[f"{prefix}_abnormal_volume"].fillna(0.0)
    return frame


def expanding_seasonal_baseline(
    weekly: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    value_col: str,
    out_col: str = "seasonal_baseline",
    min_years: int = 1,
) -> pd.DataFrame:
    """Week-of-year climatology computed from *prior years only*.

    For reference week ``w`` in year ``Y`` the baseline is the mean of the same
    ISO week in years ``< Y``. Using the full-sample climatology instead would
    be a textbook leakage, because it embeds the future into the baseline.
    """
    frame = weekly.sort_values([*group_cols, "week_start"]).copy()
    weeks = pd.to_datetime(frame["week_start"])
    frame["_iso_week"] = weeks.dt.isocalendar().week.astype(int)
    frame["_year"] = weeks.dt.isocalendar().year.astype(int)

    keys = [*group_cols, "_iso_week"]
    # Cumulative mean over previous occurrences of this (series, week-of-year)
    grouped = frame.groupby(keys, sort=False)[value_col]
    prior_sum = grouped.transform(lambda s: s.shift(1).expanding().sum())
    prior_n = grouped.transform(lambda s: s.shift(1).expanding().count())

    baseline = prior_sum / prior_n.replace(0.0, np.nan)
    # Fall back to the expanding overall mean of the series until enough history
    fallback = frame.groupby(list(group_cols), sort=False)[value_col].transform(
        lambda s: s.shift(1).expanding().mean()
    )
    frame[out_col] = baseline.where(prior_n >= min_years, fallback).fillna(0.0)
    return frame.drop(columns=["_iso_week", "_year"])


def emit_weekly_signals(
    adapter: "object",
    weekly: pd.DataFrame,
    *,
    signal_columns: Sequence[tuple[str, str]],
    family,
    denominator_col: str | None = None,
    query_template: str = "",
    note: str | None = None,
) -> tuple[list, list]:
    """Convert a weekly wide frame into :class:`SignalRecord` objects.

    Shared by every intelligence adapter so that availability stamping and
    cut-off enforcement are implemented exactly once. The reference week is
    considered complete on ``week_start + 6``; the adapter's
    ``ingestion_lag_days`` is added on top.

    Returns ``(signals, provenance)``.
    """
    from src.schemas.canonical import SignalRecord  # local import avoids a cycle

    signals: list[SignalRecord] = []
    provenance_out: list = []
    lag = int(getattr(adapter, "ingestion_lag_days", 0))
    cutoff = getattr(adapter, "cutoff")
    source = getattr(adapter, "source_name")

    for row in weekly.to_dict(orient="records"):
        week_start = pd.Timestamp(row["week_start"]).date()
        published = week_start + pd.Timedelta(days=6)
        published_date = published.date() if hasattr(published, "date") else published
        available_date = (pd.Timestamp(published_date) + pd.Timedelta(days=lag)).date()
        if available_date > cutoff:
            continue

        iso3 = str(row["iso3"])
        disease = str(row["disease_code"])
        provenance = adapter.make_provenance(  # type: ignore[attr-defined]
            record_id=f"{source}-{iso3}-{disease}-{week_start}",
            published_at=published_date,
            available_from=available_date,
            query=query_template.format(iso3=iso3, disease=disease) or None,
            notes=note,
        )
        denominator = (
            float(row[denominator_col])
            if denominator_col and denominator_col in row and pd.notna(row[denominator_col])
            else None
        )
        for signal_name, unit in signal_columns:
            value = row.get(signal_name)
            if value is None or pd.isna(value):
                continue
            signals.append(
                SignalRecord(
                    signal_id=f"{signal_name}:{iso3}:{disease}:{week_start}",
                    country_iso3=iso3,
                    disease=disease,
                    reference_date=week_start,
                    available_from=available_date,
                    signal_name=signal_name,
                    signal_family=family,
                    value=float(value),
                    unit=unit,
                    denominator=denominator,
                    provenance=provenance,
                )
            )
        provenance_out.append(provenance)
    return signals, provenance_out
