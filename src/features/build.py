"""Feature assembly: one point-in-time design matrix per as-of date.

This module is where the separation between *disease process* and *observation
process* becomes concrete. The design matrix for a given ``as_of`` is built
from six families, each answering a different question:

============================  ==========================================================
Family                        Question it answers
============================  ==========================================================
``temporal_anomaly``          Is this country's own **visible** series unusual right now?
``spatial_risk``              What is the neighbourhood doing, as of the same vintage?
``environmental``             Are conditions favourable for this pathogen, here, now?
``livestock_exposure``        How much susceptible host is at stake?
``intelligence``              Is anything being said that the official record has not caught up with?
``historical_baseline``       What is normal for this place at this time of year?
``reporting_behaviour``       How slow is this reporting stream, and how much of now is still invisible?
============================  ==========================================================

Families are not decorative: :mod:`src.alerts.counterfactual` ablates them one
at a time, so they must partition the feature space exactly.

Everything is assembled through :class:`~src.features.store.FeatureStore` and
:class:`~src.features.temporal.OfficialHistory`, both of which enforce
``available_from <= as_of``. No feature builder here touches a raw file.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.features.baseline import BASELINE_FEATURES, baseline_features
from src.features.spatial import SPATIAL_FEATURES, SpatialContext, spatial_features
from src.features.store import FeatureStore
from src.features.temporal import TEMPORAL_FEATURES, OfficialHistory, temporal_features
from src.models.delay import ReportingDelayModel
from src.schemas.enums import SignalFamily
from src.utils.config import AppConfig, get_config
from src.utils.dates import DateLike, ensure_date, iso_week_start
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "FeatureAssembler",
    "FEATURE_FAMILIES",
    "MODEL_FEATURES",
    "family_of",
    "features_in_family",
    "build_early_warning_labels",
    "build_forecast_targets",
]

# --------------------------------------------------------------------------- #
# the feature contract
# --------------------------------------------------------------------------- #
_ENVIRONMENTAL_FEATURES: tuple[str, ...] = (
    "env_suitability",
    "env_suitability_4w",
    "env_suitability_trend",
    "env_temp_anomaly_c",
    "env_precip_anomaly_mm",
    "env_cold_snap_index",
    "env_t2m_mean_c",
)

_EXPOSURE_FEATURES: tuple[str, ...] = (
    "exp_host_density_log",
    "exp_host_density_rank",
    "exp_national_stock_log",
    "exp_stock_trend",
)

_INTELLIGENCE_FEATURES: tuple[str, ...] = (
    "intel_fused_anomaly",
    "intel_fused_anomaly_lag1",
    "intel_fused_anomaly_lag4",
    "intel_effective_sources",
    "intel_max_anomaly",
    "intel_corroborating_sources",
    "gdelt_abnormal_volume",
    "gdelt_acceleration",
    "gdelt_source_diversity",
    "gdelt_baseline_ratio",
    "padiweb_abnormal_volume",
    "padiweb_event_rate",
    "padiweb_mean_relevance",
    "beacon_abnormal_volume",
    "beacon_verified_signals",
    "beacon_max_strength",
    "healthmap_abnormal_volume",
    "healthmap_unique_alerts",
    "promed_confidence_weighted",
    "eios_abnormal_volume",
)

_REPORTING_FEATURES: tuple[str, ...] = (
    "rep_expected_delay_days",
    "rep_median_delay_days",
    "rep_delay_p90_days",
    "rep_reporting_probability",
    "rep_p_reported_14d",
)

#: Feature -> evidence family. Exhaustive and disjoint by construction.
FEATURE_FAMILIES: dict[str, SignalFamily] = {
    **{name: SignalFamily.TEMPORAL_ANOMALY for name in TEMPORAL_FEATURES},
    **{name: SignalFamily.SPATIAL_RISK for name in SPATIAL_FEATURES},
    **{name: SignalFamily.HISTORICAL_BASELINE for name in BASELINE_FEATURES},
    **{name: SignalFamily.ENVIRONMENTAL for name in _ENVIRONMENTAL_FEATURES},
    **{name: SignalFamily.EXPOSURE for name in _EXPOSURE_FEATURES},
    **{name: SignalFamily.INTELLIGENCE for name in _INTELLIGENCE_FEATURES},
    **{name: SignalFamily.REPORTING_BEHAVIOUR for name in _REPORTING_FEATURES},
}

#: Ordered design-matrix column list. Models must never reorder this silently.
MODEL_FEATURES: list[str] = (
    list(TEMPORAL_FEATURES)
    + list(SPATIAL_FEATURES)
    + list(BASELINE_FEATURES)
    + list(_ENVIRONMENTAL_FEATURES)
    + list(_EXPOSURE_FEATURES)
    + list(_INTELLIGENCE_FEATURES)
    + list(_REPORTING_FEATURES)
)

#: Features whose natural "absent" value is zero rather than unknown.
_ZERO_FILL_PREFIXES = ("obs_", "spa_", "hist_", "intel_", "gdelt_", "padiweb_",
                       "beacon_", "healthmap_", "promed_", "eios_")


def family_of(feature: str) -> SignalFamily:
    """Evidence family a feature belongs to."""
    if feature in FEATURE_FAMILIES:
        return FEATURE_FAMILIES[feature]
    base = feature.split("_lag")[0]
    if base in FEATURE_FAMILIES:
        return FEATURE_FAMILIES[base]
    raise KeyError(f"Feature {feature!r} has no declared evidence family.")


def features_in_family(family: SignalFamily, among: Sequence[str] | None = None) -> list[str]:
    """All model features in *family*, optionally restricted to a subset."""
    pool = list(among) if among is not None else MODEL_FEATURES
    return [name for name in pool if FEATURE_FAMILIES.get(name) == family]


# --------------------------------------------------------------------------- #
# assembler
# --------------------------------------------------------------------------- #
class FeatureAssembler:
    """Builds point-in-time design matrices from the store and the history."""

    def __init__(
        self,
        store: FeatureStore,
        history: OfficialHistory,
        *,
        config: AppConfig | None = None,
        spatial_context: SpatialContext | None = None,
        events_for_delay: pd.DataFrame | None = None,
    ) -> None:
        self.config = config or get_config()
        self.store = store
        self.history = history
        self.spatial = spatial_context or SpatialContext(
            bandwidth_km=float(self.config.get("features.spatial_kernel_km", 900.0))
        )
        self.ewma_alpha = float(self.config.get("features.ewma_alpha", 0.30))
        self._events_for_delay = events_for_delay
        self._delay_refit_weeks = int(self.config.get("nowcast.delay_refit_interval_weeks", 8))
        self._delay_cache: dict[date, ReportingDelayModel] = {}

        self.entity_country = {key: key.split("|")[0] for key in history.entities}
        self.entity_disease = {key: key.split("|")[1] for key in history.entities}

    # ------------------------------------------------------------------ #
    # delay model vintage cache
    # ------------------------------------------------------------------ #
    def delay_model(self, as_of: DateLike) -> ReportingDelayModel | None:
        """The delay model in force at *as_of*, refit on a fixed cadence.

        The returned fit is always trained on records published on or before the
        refit date, which itself precedes *as_of*, so it cannot leak.
        """
        if self._events_for_delay is None:
            return None
        as_of_date = ensure_date(as_of)
        anchor_week = iso_week_start(as_of_date)
        # Snap to the refit grid: the most recent refit date at or before as_of.
        origin = iso_week_start(self.config.start_date)
        weeks_since = (anchor_week - origin).days // 7
        refit_week = origin + timedelta(weeks=(weeks_since // self._delay_refit_weeks) * self._delay_refit_weeks)
        if refit_week < origin:
            refit_week = origin

        if refit_week not in self._delay_cache:
            model = ReportingDelayModel(config=self.config)
            model.fit(self._events_for_delay, as_of=refit_week)
            self._delay_cache[refit_week] = model
        return self._delay_cache[refit_week]

    # ------------------------------------------------------------------ #
    # assembly
    # ------------------------------------------------------------------ #
    def assemble(self, as_of: DateLike) -> pd.DataFrame:
        """Design matrix for every entity at a single as-of date."""
        as_of_date = ensure_date(as_of)
        if as_of_date is None:
            raise ValueError("as_of must not be null.")
        reference_week = iso_week_start(as_of_date)

        blocks = [
            temporal_features(self.history, as_of_date, ewma_alpha=self.ewma_alpha),
            spatial_features(self.history, as_of_date, context=self.spatial),
            baseline_features(self.history, as_of_date),
        ]
        frame = blocks[0]
        for block in blocks[1:]:
            frame = frame.merge(block.drop(columns=["as_of"]), on="entity_key", how="left")

        # Store-backed families (environmental, exposure, intelligence)
        panel = self.store.as_of_panel(as_of_date, lags=(1, 4))
        if not panel.empty:
            keep = ["entity_key"] + [
                column for column in panel.columns
                if column in MODEL_FEATURES and column != "entity_key"
            ]
            frame = frame.merge(panel[keep], on="entity_key", how="left")

        # Reporting-behaviour family
        delay_model = self.delay_model(as_of_date)
        if delay_model is not None:
            delay_frame = delay_model.entity_features(
                self.history.entities, as_of=as_of_date, reference_week=reference_week
            )
            frame = frame.merge(delay_frame, on="entity_key", how="left")

        frame["country_iso3"] = frame["entity_key"].map(self.entity_country)
        frame["disease"] = frame["entity_key"].map(self.entity_disease)
        frame["as_of"] = pd.Timestamp(as_of_date)
        frame["reference_week"] = pd.Timestamp(reference_week)

        for feature in MODEL_FEATURES:
            if feature not in frame.columns:
                frame[feature] = np.nan
        frame = self._impute(frame)

        ordered = ["entity_key", "country_iso3", "disease", "as_of", "reference_week"]
        return frame[ordered + MODEL_FEATURES].reset_index(drop=True)

    def assemble_many(self, as_of_dates: Sequence[DateLike], *, log_every: int = 40) -> pd.DataFrame:
        """Stack design matrices across as-of dates into a training panel."""
        frames: list[pd.DataFrame] = []
        for index, as_of in enumerate(as_of_dates, start=1):
            frames.append(self.assemble(as_of))
            if log_every and index % log_every == 0:
                LOGGER.info("  assembled %s/%s as-of dates", index, len(as_of_dates))
        if not frames:
            return pd.DataFrame(columns=["entity_key", "as_of", *MODEL_FEATURES])
        out = pd.concat(frames, ignore_index=True)
        LOGGER.info(
            "Design matrix: %s rows x %s features across %s as-of dates",
            len(out), len(MODEL_FEATURES), len(as_of_dates),
        )
        return out

    @staticmethod
    def _impute(frame: pd.DataFrame) -> pd.DataFrame:
        """Fill absences with their epidemiological meaning, not with a mean.

        "No media signal" genuinely means zero anomaly, so those columns are
        zero-filled. Environmental and exposure covariates are different: a
        missing value there means *unknown*, and the panel median at that
        as-of date is the least-committal stand-in that keeps the row usable.
        """
        out = frame.copy()
        for column in MODEL_FEATURES:
            if column not in out.columns:
                continue
            series = pd.to_numeric(out[column], errors="coerce")
            if column.startswith(_ZERO_FILL_PREFIXES):
                out[column] = series.fillna(0.0)
            else:
                median = series.median()
                out[column] = series.fillna(median if np.isfinite(median) else 0.0)
            out[column] = out[column].replace([np.inf, -np.inf], 0.0)
        return out


# --------------------------------------------------------------------------- #
# targets
# --------------------------------------------------------------------------- #
def build_early_warning_labels(
    history: OfficialHistory,
    as_of_dates: Sequence[DateLike],
    *,
    config: AppConfig | None = None,
) -> pd.DataFrame:
    """Binary label: does official visibility appear or materially intensify?

    .. math::

        y = \\mathbb{1}\\left[\\, P_{(T,\\,T+H]} \\;\\ge\\;
            \\max\\left(1,\\; \\phi \\cdot \\hat{r}_T \\cdot \\tfrac{H}{7}\\right)\\right]

    where :math:`P` counts official burden *published* in the horizon,
    :math:`\\hat{r}_T` is the visible weekly run-rate at :math:`T` over the
    trailing window, and :math:`\\phi` the escalation factor.

    For a quiet entity the threshold collapses to 1 and the label means
    "emergence". For an actively reporting one it means "escalation". A single
    target, non-trivial in both regimes.
    """
    config = config or get_config()
    horizon = int(config.get("early_warning.label_horizon_days", 28))
    escalation = float(config.get("early_warning.escalation_factor", 1.5))
    run_rate_weeks = int(config.get("early_warning.run_rate_weeks", 8))
    quiet_weeks = int(config.get("early_warning.quiet_period_weeks", 8))
    corpus_end = config.data_cutoff

    rows: list[pd.DataFrame] = []
    for as_of in as_of_dates:
        as_of_date = ensure_date(as_of)
        horizon_end = as_of_date + timedelta(days=horizon)
        # A label needs its whole horizon inside the corpus, otherwise absence
        # of a notification is indistinguishable from absence of data.
        label_observable = horizon_end <= corpus_end

        visible = history.counts_as_of(as_of_date)
        w_now = history.week_position(iso_week_start(as_of_date))
        window = visible[:, max(0, w_now - run_rate_weeks + 1): w_now + 1]
        run_rate = window.sum(axis=1) / max(window.shape[1], 1)
        expected = run_rate * (horizon / 7.0)
        threshold = np.maximum(1.0, escalation * expected)

        future = history.published_between(as_of_date, horizon_end)
        label = (future >= threshold).astype(int)

        weeks_since_window = visible[:, max(0, w_now - quiet_weeks + 1): w_now + 1]
        is_quiet = (weeks_since_window.sum(axis=1) <= 0).astype(int)

        rows.append(
            pd.DataFrame(
                {
                    "entity_key": history.entities,
                    "as_of": pd.Timestamp(as_of_date),
                    "label": label,
                    "label_observable": label_observable,
                    "future_published": future,
                    "label_threshold": threshold,
                    "current_run_rate": run_rate,
                    "is_quiet": is_quiet,
                    "is_emergence": ((label == 1) & (is_quiet == 1)).astype(int),
                }
            )
        )
    out = pd.concat(rows, ignore_index=True)
    observable = out.loc[out["label_observable"]]
    LOGGER.info(
        "Early-warning labels: %s rows, %s observable, positive rate %.3f "
        "(emergence positives: %s)",
        len(out), len(observable), float(observable["label"].mean()) if len(observable) else 0.0,
        int(observable["is_emergence"].sum()),
    )
    return out


def build_forecast_targets(
    history: OfficialHistory,
    as_of_dates: Sequence[DateLike],
    horizons_days: Sequence[int],
    *,
    config: AppConfig | None = None,
) -> pd.DataFrame:
    """Eventually-reported outbreak count in each horizon week.

    The target is the *final* vintage of the target week, i.e. everything that
    was ever published about it. That is legitimate -- it is the outcome being
    predicted, not an input -- but it means a target week must be old enough to
    be essentially complete before it can be scored. ``target_complete`` marks
    the rows where that holds.
    """
    config = config or get_config()
    corpus_end = config.data_cutoff
    max_delay = int(config.get("nowcast.max_delay_days", 120))

    final = history.final_counts()
    rows: list[pd.DataFrame] = []
    for as_of in as_of_dates:
        as_of_date = ensure_date(as_of)
        for horizon in horizons_days:
            target_week = iso_week_start(as_of_date + timedelta(days=int(horizon)))
            position = history.week_position(target_week)
            if history.weeks[position] != target_week:
                continue
            target = final[:, position]
            rows.append(
                pd.DataFrame(
                    {
                        "entity_key": history.entities,
                        "as_of": pd.Timestamp(as_of_date),
                        "horizon_days": int(horizon),
                        "target_week": pd.Timestamp(target_week),
                        "target_reported_final": target,
                        "target_complete": (target_week + timedelta(days=max_delay)) <= corpus_end,
                    }
                )
            )
    if not rows:
        return pd.DataFrame(
            columns=["entity_key", "as_of", "horizon_days", "target_week",
                     "target_reported_final", "target_complete"]
        )
    out = pd.concat(rows, ignore_index=True)
    LOGGER.info(
        "Forecast targets: %s rows (%s complete) across horizons %s",
        len(out), int(out["target_complete"].sum()), list(horizons_days),
    )
    return out
