"""Vintage-aware official history and temporal features.

The officially observed series is **not a fixed object**. What the world knew
about March in early April is different from what it knows about March today,
because notifications kept arriving. Any feature computed from "the official
series" without specifying a vintage is therefore ill-defined, and in practice
optimistic: it silently uses reports that had not yet been filed.

:class:`OfficialHistory` makes the vintage explicit. It holds the reporting
triangle -- counts indexed by *when the event happened* and *when it became
knowable* -- and reconstructs, for any ``as_of``, exactly the series that was
visible at that moment.

Everything in this module is built on top of that reconstruction, so temporal
features are point-in-time correct by construction rather than by discipline.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from src.utils.dates import DateLike, ensure_date, iso_week_start, week_starts_between
from src.utils.logging_utils import get_logger
from src.utils.stats import ewma_z_score, safe_log

LOGGER = get_logger(__name__)

__all__ = ["OfficialHistory", "temporal_features", "TEMPORAL_FEATURES"]

_EPOCH = np.datetime64("1970-01-01", "D")

#: Feature names produced by :func:`temporal_features`, in emission order.
TEMPORAL_FEATURES: tuple[str, ...] = (
    "obs_last_1w",
    "obs_last_4w",
    "obs_last_8w",
    "obs_last_13w",
    "obs_last_26w",
    "obs_last_52w",
    "obs_active_weeks_52w",
    "obs_weeks_since_last",
    "obs_log_growth_4w",
    "obs_ewma_z",
    "obs_max_week_13w",
    "obs_is_currently_reporting",
)


class OfficialHistory:
    """Reporting triangle with point-in-time reconstruction."""

    def __init__(
        self,
        triangle: pd.DataFrame,
        *,
        entities: Sequence[str] | None = None,
        weeks: Sequence[date] | None = None,
    ) -> None:
        frame = triangle.copy()
        if frame.empty:
            raise ValueError("OfficialHistory requires a non-empty reporting triangle.")

        frame["reference_week"] = pd.to_datetime(frame["reference_week"]).dt.normalize()
        frame["available_week"] = pd.to_datetime(frame["available_week"]).dt.normalize()
        frame["count"] = pd.to_numeric(frame["count"], errors="coerce").fillna(0.0)

        self.entities: list[str] = sorted(entities) if entities is not None else sorted(
            frame["entity_key"].unique().tolist()
        )
        if weeks is None:
            weeks = week_starts_between(
                frame["reference_week"].min().date(), frame["reference_week"].max().date()
            )
        self.weeks: list[date] = list(weeks)

        self._entity_index = {key: i for i, key in enumerate(self.entities)}
        self._week_index = {week: i for i, week in enumerate(self.weeks)}
        self.n_entities = len(self.entities)
        self.n_weeks = len(self.weeks)

        frame = frame.loc[
            frame["entity_key"].isin(self._entity_index)
            & frame["reference_week"].dt.date.isin(self._week_index)
        ]
        self._e = frame["entity_key"].map(self._entity_index).to_numpy(dtype=int)
        self._w = frame["reference_week"].dt.date.map(self._week_index).to_numpy(dtype=int)
        self._value = frame["count"].to_numpy(dtype=float)
        self._avail_day = (
            frame["available_week"].to_numpy(dtype="datetime64[D]") - _EPOCH
        ).astype("int64")
        # Availability is at the day the record was published, not the Monday of
        # that week; the triangle carries the week, so use the week's Monday and
        # let the caller compare against the as-of date.
        self._order = np.argsort(self._avail_day, kind="mergesort")

        self.entity_country = {key: key.split("|")[0] for key in self.entities}
        self.entity_disease = {key: key.split("|")[1] for key in self.entities}
        LOGGER.debug(
            "OfficialHistory: %s entities x %s weeks, %s triangle cells",
            self.n_entities, self.n_weeks, len(self._value),
        )

    # ------------------------------------------------------------------ #
    # vintage reconstruction
    # ------------------------------------------------------------------ #
    def counts_as_of(self, as_of: DateLike) -> np.ndarray:
        """``(n_entities, n_weeks)`` array of the series visible at *as_of*.

        Weeks after *as_of* are zeroed: they have not happened yet.
        """
        as_of_date = ensure_date(as_of)
        as_of_day = int((np.datetime64(as_of_date, "D") - _EPOCH).astype("int64"))
        current_week = iso_week_start(as_of_date)
        w_now = self.week_position(current_week)

        mask = (self._avail_day <= as_of_day) & (self._w <= w_now)
        flat = np.bincount(
            self._e[mask] * self.n_weeks + self._w[mask],
            weights=self._value[mask],
            minlength=self.n_entities * self.n_weeks,
        )
        counts = flat.reshape(self.n_entities, self.n_weeks)
        if w_now + 1 < self.n_weeks:
            counts[:, w_now + 1:] = 0.0
        return counts

    def published_between(self, start: DateLike, end: DateLike) -> np.ndarray:
        """Official burden that *became knowable* in ``(start, end]``.

        This is the quantity the early-warning label is built on: not what
        happened in the window, but what the world was told in the window.
        """
        start_day = int((np.datetime64(ensure_date(start), "D") - _EPOCH).astype("int64"))
        end_day = int((np.datetime64(ensure_date(end), "D") - _EPOCH).astype("int64"))
        mask = (self._avail_day > start_day) & (self._avail_day <= end_day)
        return np.bincount(
            self._e[mask], weights=self._value[mask], minlength=self.n_entities
        ).astype(float)

    def occurred_between(self, start: DateLike, end: DateLike) -> np.ndarray:
        """Final (fully-reported) burden with a reference week in ``(start, end]``.

        Evaluation and forecast targets only: uses records that were published
        after the analysis date, so it must never appear in a feature.
        """
        weeks = np.array([np.datetime64(week, "D") for week in self.weeks])
        week_days = (weeks - _EPOCH).astype("int64")
        start_day = int((np.datetime64(ensure_date(start), "D") - _EPOCH).astype("int64"))
        end_day = int((np.datetime64(ensure_date(end), "D") - _EPOCH).astype("int64"))
        in_window = (week_days[self._w] > start_day) & (week_days[self._w] <= end_day)
        return np.bincount(
            self._e[in_window], weights=self._value[in_window], minlength=self.n_entities
        ).astype(float)

    def final_counts(self) -> np.ndarray:
        """The fully-reported series using everything in the corpus.

        Only legitimate for *evaluation* of past weeks, never as a feature.
        """
        flat = np.bincount(
            self._e * self.n_weeks + self._w,
            weights=self._value,
            minlength=self.n_entities * self.n_weeks,
        )
        return flat.reshape(self.n_entities, self.n_weeks)

    def week_position(self, week: date) -> int:
        """Index of *week* on the grid, clipped into range."""
        if week in self._week_index:
            return self._week_index[week]
        if week < self.weeks[0]:
            return 0
        earlier = [i for i, candidate in enumerate(self.weeks) if candidate <= week]
        return earlier[-1] if earlier else 0

    def series_frame(self, as_of: DateLike) -> pd.DataFrame:
        """Long frame of the visible series, for plotting and diagnostics."""
        counts = self.counts_as_of(as_of)
        return pd.DataFrame(
            {
                "entity_key": np.repeat(self.entities, self.n_weeks),
                "week_start": np.tile(self.weeks, self.n_entities),
                "observed": counts.reshape(-1),
            }
        )

    def delay_profile(self) -> pd.DataFrame:
        """Empirical distribution of reporting delay in whole weeks."""
        delay_weeks = (self._avail_day - self._week_number()) // 7
        frame = pd.DataFrame({"delay_weeks": np.clip(delay_weeks, 0, None), "count": self._value})
        return (
            frame.groupby("delay_weeks", as_index=False)["count"].sum()
            .assign(share=lambda d: d["count"] / d["count"].sum())
        )

    def _week_number(self) -> np.ndarray:
        week_days = np.array(
            [(np.datetime64(week, "D") - _EPOCH).astype("int64") for week in self.weeks]
        )
        return week_days[self._w]


# --------------------------------------------------------------------------- #
# temporal features
# --------------------------------------------------------------------------- #
def temporal_features(
    history: OfficialHistory,
    as_of: DateLike,
    *,
    ewma_alpha: float = 0.30,
) -> pd.DataFrame:
    """Features describing each entity's own officially visible trajectory.

    All statistics are computed on the *vintage* visible at *as_of*, so a
    country that has simply not filed yet looks quiet -- which is exactly the
    blind spot the nowcast and the intelligence signals exist to cover.
    """
    counts = history.counts_as_of(as_of)
    as_of_date = ensure_date(as_of)
    w_now = history.week_position(iso_week_start(as_of_date))
    visible = counts[:, : w_now + 1]
    n_entities = visible.shape[0]

    def window_sum(weeks: int) -> np.ndarray:
        if visible.shape[1] == 0:
            return np.zeros(n_entities)
        return visible[:, -weeks:].sum(axis=1)

    last_1 = window_sum(1)
    last_4 = window_sum(4)
    last_8 = window_sum(8)
    last_13 = window_sum(13)
    last_26 = window_sum(26)
    last_52 = window_sum(52)

    previous_4 = (
        visible[:, -8:-4].sum(axis=1) if visible.shape[1] >= 8 else np.zeros(n_entities)
    )
    log_growth = safe_log(last_4) - safe_log(previous_4)

    active_weeks = (visible[:, -52:] > 0).sum(axis=1).astype(float)
    max_week_13 = visible[:, -13:].max(axis=1) if visible.shape[1] else np.zeros(n_entities)

    # Weeks since the most recent officially visible activity
    weeks_since = np.full(n_entities, float(min(visible.shape[1], 260)))
    any_activity = visible > 0
    has_any = any_activity.any(axis=1)
    last_index = visible.shape[1] - 1 - np.argmax(any_activity[:, ::-1], axis=1)
    weeks_since[has_any] = (visible.shape[1] - 1 - last_index[has_any]).astype(float)

    ewma_z = np.array(
        [ewma_z_score(safe_log(row), alpha=ewma_alpha)[-1] if row.size else 0.0 for row in visible]
    )

    frame = pd.DataFrame(
        {
            "entity_key": history.entities,
            "obs_last_1w": last_1,
            "obs_last_4w": last_4,
            "obs_last_8w": last_8,
            "obs_last_13w": last_13,
            "obs_last_26w": last_26,
            "obs_last_52w": last_52,
            "obs_active_weeks_52w": active_weeks,
            "obs_weeks_since_last": weeks_since,
            "obs_log_growth_4w": log_growth,
            "obs_ewma_z": ewma_z,
            "obs_max_week_13w": max_week_13,
            "obs_is_currently_reporting": (last_4 > 0).astype(float),
        }
    )
    frame["as_of"] = pd.Timestamp(as_of_date)
    return frame
