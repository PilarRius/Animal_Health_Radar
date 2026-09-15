"""Point-in-time feature store.

Every feature value is stored with three dates, not one:

``reference_date``
    the week the value describes;
``available_from``
    the date the value became knowable;
``as_of`` (supplied at read time)
    the knowledge cut-off of the prediction being made.

A value is usable if and only if ``available_from <= as_of``. Nothing else in
the codebase is allowed to make that judgement.

Two representations are maintained deliberately:

*The long frame* is the source of truth. It is what gets written to Parquet,
what the provenance screen displays, and what the naive reference implementation
in the leakage tests reads.

*The dense cube* is a derived array layout (entity x week x feature, plus a
parallel availability array) that makes ``as_of`` reads a couple of vectorised
operations. Building point-in-time training sets requires hundreds of reads, and
a slow store is a store people work around. ``tests/leakage`` asserts the two
paths agree exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.utils.asof import AsOfViolationError
from src.utils.dates import DateLike, ensure_date, iso_week_start, week_starts_between
from src.utils.io import read_parquet, write_parquet
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["FeatureStore", "DenseCube", "STORE_COLUMNS"]

STORE_COLUMNS: list[str] = [
    "entity_key",
    "country_iso3",
    "disease",
    "reference_week",
    "feature",
    "value",
    "available_from",
    "family",
    "source",
]

_EPOCH = np.datetime64("1970-01-01", "D")


def _to_day_number(values: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Convert dates to integer days since the epoch (NaT -> +inf)."""
    arr = pd.to_datetime(values, errors="coerce").to_numpy(dtype="datetime64[D]")
    out = (arr - _EPOCH).astype("float64")
    out[np.isnat(arr)] = np.inf
    return out


def _day_number(value: DateLike) -> float:
    resolved = ensure_date(value)
    if resolved is None:
        raise ValueError("as_of must not be null.")
    return float((np.datetime64(resolved, "D") - _EPOCH).astype("int64"))


@dataclass
class DenseCube:
    """Array layout of the store: values and availability on a fixed grid."""

    entities: list[str]
    weeks: list[date]
    features: list[str]
    values: np.ndarray        # (E, W, F) float, NaN where absent
    available: np.ndarray     # (E, W, F) float day-numbers, +inf where absent

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.values.shape


class FeatureStore:
    """Long, append-only, point-in-time-correct feature table."""

    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        if frame is None or frame.empty:
            self._frame = pd.DataFrame(columns=STORE_COLUMNS)
        else:
            self._frame = self._coerce(frame)
        self._cube: DenseCube | None = None

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce(frame: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in STORE_COLUMNS if column not in frame.columns]
        if missing:
            raise KeyError(f"Feature store frame is missing columns: {missing}")
        out = frame[STORE_COLUMNS].copy()
        out["reference_week"] = pd.to_datetime(out["reference_week"], errors="coerce").dt.normalize()
        out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce").dt.normalize()
        out["value"] = pd.to_numeric(out["value"], errors="coerce")

        bad_dates = int(out["reference_week"].isna().sum() + out["available_from"].isna().sum())
        if bad_dates:
            LOGGER.warning("Dropping %s feature rows with unparseable dates.", bad_dates)
            out = out.loc[out["reference_week"].notna() & out["available_from"].notna()]

        leaking = out["available_from"] < out["reference_week"]
        if bool(leaking.any()):
            examples = out.loc[leaking, "feature"].unique()[:5]
            raise AsOfViolationError(
                f"{int(leaking.sum())} feature row(s) claim to be available before the week they "
                f"describe (e.g. {list(examples)}). This would leak the future into the past."
            )
        return out.loc[out["value"].notna()].reset_index(drop=True)

    def add(self, frame: pd.DataFrame) -> FeatureStore:
        """Append rows, invalidating the dense cache."""
        if frame is None or frame.empty:
            return self
        self._frame = pd.concat([self._frame, self._coerce(frame)], ignore_index=True)
        self._cube = None
        return self

    @classmethod
    def from_long(cls, frame: pd.DataFrame) -> FeatureStore:
        return cls(frame)

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def save(self, path) -> None:
        write_parquet(self._frame, path)

    @classmethod
    def load(cls, path) -> FeatureStore:
        return cls(read_parquet(path))

    # ------------------------------------------------------------------ #
    # inspection
    # ------------------------------------------------------------------ #
    @property
    def long(self) -> pd.DataFrame:
        """The authoritative long table (a copy)."""
        return self._frame.copy()

    @property
    def features(self) -> list[str]:
        return sorted(self._frame["feature"].unique().tolist())

    @property
    def entities(self) -> list[str]:
        return sorted(self._frame["entity_key"].unique().tolist())

    def families(self) -> dict[str, list[str]]:
        grouped = self._frame.groupby("family")["feature"].unique()
        return {family: sorted(values.tolist()) for family, values in grouped.items()}

    def feature_family_map(self) -> dict[str, str]:
        pairs = self._frame[["feature", "family"]].drop_duplicates()
        return dict(zip(pairs["feature"], pairs["family"], strict=True))

    def __len__(self) -> int:
        return len(self._frame)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<FeatureStore rows={len(self._frame)} entities={len(self.entities)} "
            f"features={len(self.features)}>"
        )

    # ------------------------------------------------------------------ #
    # point-in-time reads
    # ------------------------------------------------------------------ #
    def as_of_long(
        self,
        as_of: DateLike,
        *,
        features: Sequence[str] | None = None,
        lookback_weeks: int | None = None,
    ) -> pd.DataFrame:
        """Rows knowable at *as_of*, reference week not in the future.

        Reference implementation: straightforward boolean masks on the long
        frame. Correctness first; :meth:`as_of_panel` is the fast path.
        """
        cutoff = pd.Timestamp(ensure_date(as_of))
        frame = self._frame
        mask = (frame["available_from"] <= cutoff) & (frame["reference_week"] <= cutoff)
        if features is not None:
            mask &= frame["feature"].isin(list(features))
        if lookback_weeks is not None:
            earliest = cutoff - pd.Timedelta(weeks=int(lookback_weeks))
            mask &= frame["reference_week"] >= earliest
        return frame.loc[mask].reset_index(drop=True).copy()

    def latest_as_of(self, as_of: DateLike, *, features: Sequence[str] | None = None) -> pd.DataFrame:
        """Most recent knowable value per (entity, feature) at *as_of*."""
        eligible = self.as_of_long(as_of, features=features)
        if eligible.empty:
            return eligible
        eligible = eligible.sort_values(["reference_week", "available_from"], kind="mergesort")
        return (
            eligible.groupby(["entity_key", "feature"], as_index=False, sort=False)
            .tail(1)
            .reset_index(drop=True)
        )

    # -- dense fast path --------------------------------------------------- #
    def build_cube(self, weeks: Sequence[date] | None = None) -> DenseCube:
        """Materialise the dense (entity x week x feature) arrays."""
        if self._cube is not None and weeks is None:
            return self._cube
        if self._frame.empty:
            cube = DenseCube([], [], [], np.zeros((0, 0, 0)), np.zeros((0, 0, 0)))
            self._cube = cube
            return cube

        if weeks is None:
            first = self._frame["reference_week"].min().date()
            last = self._frame["reference_week"].max().date()
            weeks = week_starts_between(first, last)

        entities = self.entities
        features = self.features
        entity_index = {key: i for i, key in enumerate(entities)}
        week_index = {week: i for i, week in enumerate(weeks)}
        feature_index = {name: i for i, name in enumerate(features)}

        shape = (len(entities), len(weeks), len(features))
        values = np.full(shape, np.nan, dtype="float64")
        available = np.full(shape, np.inf, dtype="float64")

        frame = self._frame.sort_values("available_from", kind="mergesort")
        e_idx = frame["entity_key"].map(entity_index).to_numpy()
        w_idx = frame["reference_week"].dt.date.map(week_index).to_numpy()
        f_idx = frame["feature"].map(feature_index).to_numpy()
        valid = pd.notna(w_idx)
        e_idx = e_idx[valid].astype(int)
        w_idx = w_idx[valid].astype(int)
        f_idx = f_idx[valid].astype(int)

        # Sorted by availability, so a later assignment is a later revision:
        # exactly the vintage semantics we want.
        values[e_idx, w_idx, f_idx] = frame.loc[valid, "value"].to_numpy(dtype=float)
        available[e_idx, w_idx, f_idx] = _to_day_number(frame.loc[valid, "available_from"])

        cube = DenseCube(
            entities=entities, weeks=list(weeks), features=features,
            values=values, available=available,
        )
        self._cube = cube
        LOGGER.debug("Feature cube built: %s entities x %s weeks x %s features", *cube.shape)
        return cube

    def as_of_panel(
        self,
        as_of: DateLike,
        *,
        lags: Sequence[int] = (1, 4),
        features: Sequence[str] | None = None,
        max_staleness_weeks: int = 12,
    ) -> pd.DataFrame:
        """Wide, one row per entity, of everything knowable at *as_of*.

        For each feature three things are produced:

        ``{feature}``
            the most recent usable value (carried forward, as an analyst would);
        ``{feature}_staleness_weeks``
            how old that value is -- an honest measure of how much of the panel
            is actually being informed by fresh data;
        ``{feature}_lag{k}``
            the value that described the week ``k`` weeks before the current
            one, again only if it was already published at *as_of*.

        Values older than ``max_staleness_weeks`` are dropped rather than
        carried forward indefinitely.
        """
        cube = self.build_cube()
        if not cube.entities:
            return pd.DataFrame()

        as_of_date = ensure_date(as_of)
        as_of_day = _day_number(as_of_date)
        current_week = iso_week_start(as_of_date)

        week_positions = {week: i for i, week in enumerate(cube.weeks)}
        if current_week in week_positions:
            w_now = week_positions[current_week]
        else:
            earlier = [i for i, week in enumerate(cube.weeks) if week <= current_week]
            if not earlier:
                return pd.DataFrame()
            w_now = earlier[-1]

        if features is None:
            f_sel = np.arange(len(cube.features))
            feature_names = cube.features
        else:
            wanted = [f for f in features if f in cube.features]
            f_sel = np.array([cube.features.index(f) for f in wanted], dtype=int)
            feature_names = wanted
        if len(f_sel) == 0:
            return pd.DataFrame()

        values = cube.values[:, : w_now + 1, :][:, :, f_sel]         # (E, W', F')
        available = cube.available[:, : w_now + 1, :][:, :, f_sel]
        usable = (available <= as_of_day) & np.isfinite(values)

        data: dict[str, np.ndarray] = {}

        # --- most recent usable observation, with staleness ---------------- #
        reversed_usable = usable[:, ::-1, :]
        any_usable = reversed_usable.any(axis=1)
        first_hit = reversed_usable.argmax(axis=1)                    # (E, F')
        staleness = np.where(any_usable, first_hit, np.nan).astype(float)
        latest_index = (w_now - first_hit).astype(int)

        e_grid, f_grid = np.meshgrid(
            np.arange(values.shape[0]), np.arange(values.shape[2]), indexing="ij"
        )
        latest_values = values[e_grid, latest_index, f_grid]
        too_stale = staleness > float(max_staleness_weeks)
        latest_values = np.where(any_usable & ~too_stale, latest_values, np.nan)
        staleness = np.where(any_usable & ~too_stale, staleness, np.nan)

        for j, name in enumerate(feature_names):
            data[name] = latest_values[:, j]
            data[f"{name}_staleness_weeks"] = staleness[:, j]

        # --- explicit lags -------------------------------------------------- #
        for lag in lags:
            index = w_now - int(lag)
            if index < 0:
                continue
            lag_values = np.where(usable[:, index, :], values[:, index, :], np.nan)
            for j, name in enumerate(feature_names):
                data[f"{name}_lag{int(lag)}"] = lag_values[:, j]

        panel = pd.DataFrame(data, index=pd.Index(cube.entities, name="entity_key"))
        panel.insert(0, "as_of", pd.Timestamp(as_of_date))
        panel.insert(1, "reference_week", pd.Timestamp(cube.weeks[w_now]))
        return panel.reset_index()

    # ------------------------------------------------------------------ #
    # auditing
    # ------------------------------------------------------------------ #
    def availability_profile(self) -> pd.DataFrame:
        """Median publication lag per feature family: the store's own audit."""
        if self._frame.empty:
            return pd.DataFrame(columns=["family", "feature", "median_lag_days", "n_rows"])
        frame = self._frame.copy()
        frame["lag_days"] = (frame["available_from"] - frame["reference_week"]).dt.days
        return (
            frame.groupby(["family", "feature"], as_index=False)
            .agg(median_lag_days=("lag_days", "median"),
                 max_lag_days=("lag_days", "max"),
                 n_rows=("value", "size"))
            .sort_values(["family", "feature"])
            .reset_index(drop=True)
        )
