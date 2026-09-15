"""Historical baseline features: what is normal for this place at this time?

Without a baseline, "five outbreaks reported" is uninterpretable. Five in
December in a country that always reports HPAI in December is business as
usual; five in June is an emergency.

The baseline here is a **week-of-year climatology built from prior years of the
vintage visible at as_of**. Two properties matter:

* it uses only earlier calendar years, so it never contains the very week it is
  used to judge;
* it is computed from the visible vintage, so a country whose reports for last
  December arrived late has a correspondingly weaker December baseline -- which
  is the honest representation of what was known.

A smoothing window of +/- 2 ISO weeks is applied because a single calendar week
across three years is far too thin to estimate a seasonal level.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.temporal import OfficialHistory
from src.utils.dates import DateLike, ensure_date, iso_week_start
from src.utils.logging_utils import get_logger
from src.utils.stats import safe_log

LOGGER = get_logger(__name__)

__all__ = ["baseline_features", "BASELINE_FEATURES"]

BASELINE_FEATURES: tuple[str, ...] = (
    "hist_seasonal_baseline",
    "hist_seasonal_baseline_log",
    "hist_excess_over_baseline",
    "hist_years_of_history",
    "hist_ever_reported",
    "hist_annual_mean",
)


def baseline_features(
    history: OfficialHistory,
    as_of: DateLike,
    *,
    week_window: int = 2,
    horizon_weeks: int = 4,
) -> pd.DataFrame:
    """Seasonal climatology of officially reported activity, vintage-correct.

    Parameters
    ----------
    week_window:
        Half-width, in ISO weeks, of the smoothing window around the target week.
    horizon_weeks:
        Length of the recent window compared against the baseline to form the
        excess statistic.
    """
    as_of_date = ensure_date(as_of)
    current_week = iso_week_start(as_of_date)
    w_now = history.week_position(current_week)
    counts = history.counts_as_of(as_of)[:, : w_now + 1]

    weeks = history.weeks[: w_now + 1]
    iso_weeks = np.array([week.isocalendar().week for week in weeks], dtype=int)
    years = np.array([week.isocalendar().year for week in weeks], dtype=int)

    target_iso = current_week.isocalendar().week
    current_year = current_week.isocalendar().year

    # Circular window over ISO week numbers, previous calendar years only.
    distance = np.minimum(
        np.abs(iso_weeks - target_iso), 53 - np.abs(iso_weeks - target_iso)
    )
    in_window = (distance <= week_window) & (years < current_year)

    n_entities = counts.shape[0]
    if in_window.any():
        baseline = counts[:, in_window].mean(axis=1)
        years_of_history = float(len(np.unique(years[in_window])))
    else:
        baseline = np.zeros(n_entities)
        years_of_history = 0.0

    recent = (
        counts[:, -horizon_weeks:].mean(axis=1) if counts.shape[1] else np.zeros(n_entities)
    )
    # Excess expressed on a variance-stabilised scale so that a jump from 0 to 2
    # is not treated as an infinite increase.
    excess = (recent - baseline) / np.sqrt(np.clip(baseline, 0.0, None) + 1.0)

    annual_mean = counts.mean(axis=1) * 52.0 if counts.shape[1] else np.zeros(n_entities)
    ever_reported = (counts.sum(axis=1) > 0).astype(float)

    frame = pd.DataFrame(
        {
            "entity_key": history.entities,
            "hist_seasonal_baseline": baseline,
            "hist_seasonal_baseline_log": safe_log(baseline),
            "hist_excess_over_baseline": excess,
            "hist_years_of_history": years_of_history,
            "hist_ever_reported": ever_reported,
            "hist_annual_mean": annual_mean,
        }
    )
    frame["as_of"] = pd.Timestamp(as_of_date)
    return frame
