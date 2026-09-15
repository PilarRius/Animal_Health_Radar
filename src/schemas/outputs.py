"""Output contracts: what the models are allowed to tell the world.

The three objects mirror the three questions the Radar answers:

:class:`NowcastObject`
    *What is probably happening now, and how much of it is invisible?*

:class:`ForecastObject`
    *Where is this going over the next 7/14/28 days, with what uncertainty?*

:class:`AlertObject`
    *Should a human look at this, why, and on what evidence?*

Every numeric field on these objects is produced by a fitted model or an
explicit configured rule. None of them may be authored by hand for display.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from src.schemas.canonical import make_entity_key
from src.schemas.enums import AlertLevel, SignalFamily
from src.schemas.provenance import SourceProvenance

__all__ = [
    "EvidenceContribution",
    "CounterfactualAblation",
    "ReportingEstimate",
    "NowcastObject",
    "ForecastObject",
    "AlertObject",
    "Explanation",
]


# --------------------------------------------------------------------------- #
# explanation components
# --------------------------------------------------------------------------- #
class EvidenceContribution(BaseModel):
    """One feature's signed contribution to the early-warning score.

    ``contribution`` is on the log-odds scale (SHAP value or
    standardised-coefficient product), so contributions are additive.
    """

    model_config = ConfigDict(extra="forbid")

    feature: str
    family: SignalFamily
    value: float | None = Field(None, description="Feature value at as_of.")
    contribution: float = Field(..., description="Signed log-odds contribution.")
    percentile: float | None = Field(
        None, ge=0.0, le=1.0, description="Where this value sits in the training distribution."
    )
    description: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def direction(self) -> str:
        if self.contribution > 1e-6:
            return "increases_risk"
        if self.contribution < -1e-6:
            return "decreases_risk"
        return "neutral"


class CounterfactualAblation(BaseModel):
    """Effect of removing one evidence family, computed by re-scoring the model.

    The ablated scenario replaces every feature in the family with its
    training-set baseline (median) and re-runs the fitted model. This is a
    genuine model evaluation, not an attribution heuristic.
    """

    model_config = ConfigDict(extra="forbid")

    family: SignalFamily
    n_features_ablated: int = Field(..., ge=0)
    probability_with: float = Field(..., ge=0.0, le=1.0)
    probability_without: float = Field(..., ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delta(self) -> float:
        """How much of the current probability this family is responsible for."""
        return self.probability_with - self.probability_without

    @computed_field  # type: ignore[prop-decorator]
    @property
    def interpretation(self) -> str:
        delta = self.delta
        if abs(delta) < 0.01:
            return f"Removing {self.family} barely changes the assessment."
        direction = "falls" if delta > 0 else "rises"
        return (
            f"Without {self.family} evidence the probability {direction} "
            f"from {self.probability_with:.0%} to {self.probability_without:.0%}."
        )


class Explanation(BaseModel):
    """Human-readable rationale assembled from computed quantities only."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    narrative: str
    top_contributions: list[EvidenceContribution] = Field(default_factory=list)
    counterfactuals: list[CounterfactualAblation] = Field(default_factory=list)
    method: str = Field(..., description="shap | coefficient | permutation")
    caveats: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# reporting process
# --------------------------------------------------------------------------- #
class ReportingEstimate(BaseModel):
    """Fitted description of the observation process for one entity."""

    model_config = ConfigDict(extra="forbid")

    entity_key: str
    as_of: date
    distribution: str = Field(..., description="lognormal | negbin")
    expected_reporting_delay: float = Field(
        ..., ge=0.0, description="Mean onset -> notification delay in days."
    )
    median_reporting_delay: float = Field(..., ge=0.0)
    delay_p90: float = Field(..., ge=0.0)
    reporting_probability: float = Field(
        ..., ge=0.0, le=1.0,
        description="P(an event with onset in the current reference week is already reported).",
    )
    p_reported_by: dict[str, float] = Field(
        default_factory=dict, description="P(reported within k days) for k in {7,14,28,60}."
    )
    n_observations: int = Field(..., ge=0, description="Delays used to fit (right-truncated).")
    pooled_with_global: bool = Field(
        False, description="True when the entity was shrunk towards the global fit."
    )
    shrinkage_weight: float = Field(
        0.0, ge=0.0, le=1.0, description="Weight placed on the entity-specific fit."
    )


# --------------------------------------------------------------------------- #
# nowcast
# --------------------------------------------------------------------------- #
class NowcastObject(BaseModel):
    """Estimate of current latent disease activity and its invisible fraction."""

    model_config = ConfigDict(extra="forbid")

    entity_key: str
    country_iso3: str
    disease: str
    as_of: date = Field(..., description="Knowledge cut-off of this estimate.")
    reference_week: date = Field(..., description="Week being nowcast (Monday).")

    # --- the observation process ------------------------------------------- #
    observed_disease_burden: float = Field(
        ..., ge=0.0, description="Outbreaks officially visible at as_of for this week."
    )
    reporting_probability: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of this week's events expected visible yet."
    )
    expected_reporting_delay: float = Field(..., ge=0.0, description="Days, onset -> notification.")

    # --- the latent process -------------------------------------------------- #
    latent_disease_estimate: float = Field(
        ..., ge=0.0, description="Estimated true outbreaks in the reference week."
    )
    nowcast_lower: float = Field(..., ge=0.0)
    nowcast_upper: float = Field(..., ge=0.0)
    interval_level: float = Field(0.90, gt=0.0, lt=1.0)

    # --- the gap -------------------------------------------------------------- #
    estimated_hidden_burden: float = Field(
        ..., description="latent - observed; can be ~0 for complete weeks."
    )
    reporting_gap: float = Field(
        ..., ge=0.0, le=1.0, description="Hidden fraction of the latent burden."
    )
    reporting_gap_band: str = Field("minor", description="minor | moderate | severe")

    # --- assumptions made explicit ------------------------------------------- #
    ascertainment_mean: float = Field(
        1.0, gt=0.0, le=1.0,
        description="Assumed P(a true outbreak is ever detected). PRIOR, not an estimate.",
    )
    ascertainment_source: str = Field(
        "config", description="Where the ascertainment assumption came from."
    )

    method: str = Field(..., description="Nowcast estimator identifier.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    n_contributing_records: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _interval_order(self) -> NowcastObject:
        if self.nowcast_lower > self.nowcast_upper:
            raise ValueError(
                f"Nowcast interval inverted for {self.entity_key} @ {self.as_of}: "
                f"[{self.nowcast_lower}, {self.nowcast_upper}]"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def interval_width(self) -> float:
        return self.nowcast_upper - self.nowcast_lower


# --------------------------------------------------------------------------- #
# forecast
# --------------------------------------------------------------------------- #
class ForecastObject(BaseModel):
    """Probabilistic short-term forecast for one entity and one horizon."""

    model_config = ConfigDict(extra="forbid")

    entity_key: str
    country_iso3: str
    disease: str
    as_of: date
    horizon_days: int = Field(..., gt=0)
    target_week: date = Field(..., description="Week the forecast refers to (Monday).")
    target: str = Field("latent", description="latent | reported")

    point: float = Field(..., ge=0.0, description="Predictive median.")
    mean: float = Field(..., ge=0.0)
    lower: float = Field(..., ge=0.0)
    upper: float = Field(..., ge=0.0)
    interval_level: float = Field(0.90, gt=0.0, lt=1.0)
    quantiles: dict[str, float] = Field(
        default_factory=dict, description="Full predictive quantile set, keyed by level."
    )

    # --- decision-relevant probabilities ------------------------------------ #
    p_exceed_threshold: float = Field(..., ge=0.0, le=1.0)
    exceedance_threshold: float = Field(..., ge=0.0)
    p_increase: float = Field(..., ge=0.0, le=1.0, description="P(above current level + margin).")
    p_new_outbreak: float = Field(..., ge=0.0, le=1.0, description="P(at least one outbreak).")

    # --- provenance of the number ------------------------------------------- #
    method: str
    ensemble_weights: dict[str, float] = Field(default_factory=dict)
    dispersion: float | None = Field(None, ge=0.0, description="Fitted NB dispersion alpha.")

    @model_validator(mode="after")
    def _interval_order(self) -> ForecastObject:
        if self.lower > self.upper:
            raise ValueError(f"Forecast interval inverted for {self.entity_key} @ {self.as_of}.")
        return self


# --------------------------------------------------------------------------- #
# alert
# --------------------------------------------------------------------------- #
class AlertObject(BaseModel):
    """The composite object surfaced by the Radar for one country x disease x as-of.

    It bundles the three model outputs plus the evidence that justifies them.
    Everything here is computed; nothing is authored for display.
    """

    model_config = ConfigDict(extra="forbid")

    # --- identity ------------------------------------------------------------ #
    alert_id: str
    country_iso3: str
    country_name: str | None = None
    disease: str
    as_of: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now().replace(microsecond=0))

    # --- early warning -------------------------------------------------------- #
    early_warning_score: float = Field(
        ..., description="Uncalibrated model score (log-odds scale)."
    )
    early_warning_probability: float = Field(
        ..., ge=0.0, le=1.0,
        description="Calibrated P(officially visible within the label horizon).",
    )
    label_horizon_days: int = Field(28, gt=0)
    alert_level: AlertLevel = AlertLevel.NONE

    # --- latent state --------------------------------------------------------- #
    latent_disease_estimate: float = Field(..., ge=0.0)
    observed_disease_burden: float = Field(..., ge=0.0)
    estimated_hidden_burden: float = Field(...)
    reporting_gap: float = Field(..., ge=0.0, le=1.0)
    nowcast_lower: float = Field(..., ge=0.0)
    nowcast_upper: float = Field(..., ge=0.0)

    # --- observation process -------------------------------------------------- #
    reporting_probability: float = Field(..., ge=0.0, le=1.0)
    expected_reporting_delay: float = Field(..., ge=0.0)

    # --- forecast ------------------------------------------------------------- #
    forecast_7d: float | None = None
    forecast_7d_lower: float | None = None
    forecast_7d_upper: float | None = None
    forecast_14d: float | None = None
    forecast_14d_lower: float | None = None
    forecast_14d_upper: float | None = None
    forecast_28d: float | None = None
    forecast_28d_lower: float | None = None
    forecast_28d_upper: float | None = None
    p_exceed_14d: float | None = Field(None, ge=0.0, le=1.0)
    p_increase_14d: float | None = Field(None, ge=0.0, le=1.0)
    p_new_outbreak_28d: float | None = Field(None, ge=0.0, le=1.0)

    # --- evidence components (each in [0, 1] unless noted) --------------------- #
    temporal_anomaly: float = Field(..., description="EWMA control-chart z-score.")
    spatial_risk: float = Field(..., ge=0.0, description="Neighbour-weighted latent activity.")
    environmental_signal: float = Field(..., description="Disease-specific suitability index.")
    livestock_exposure: float = Field(..., ge=0.0, description="Log host density, standardised.")
    intelligence_signal: float = Field(..., description="Fused media/aggregator anomaly.")
    historical_baseline: float = Field(
        ..., ge=0.0, description="Seasonal climatology of reported activity."
    )

    # --- evidence quality ------------------------------------------------------ #
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_band: str = Field("low", description="low | moderate | high")
    evidence_independence: float = Field(
        ..., ge=0.0,
        description="Effective number of independent evidence clusters supporting the signal.",
    )
    contributing_sources: list[str] = Field(default_factory=list)
    n_records_used: int = Field(0, ge=0)

    # --- priority -------------------------------------------------------------- #
    investigation_priority: float = Field(
        ..., ge=0.0, le=1.0, description="Composite used by the global radar choropleth."
    )
    priority_band: str = Field("low", description="low | moderate | high | very_high")

    # --- explanation and audit -------------------------------------------------- #
    explanation: Explanation
    provenance: list[SourceProvenance] = Field(default_factory=list)
    recommended_action: str | None = None
    data_realism: str = Field(
        "synthetic", description="Realism label of the underlying corpus."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entity_key(self) -> str:
        return make_entity_key(self.country_iso3, self.disease)

    @model_validator(mode="after")
    def _coherence(self) -> AlertObject:
        if self.nowcast_lower > self.nowcast_upper:
            raise ValueError(f"Alert {self.alert_id}: inverted nowcast interval.")
        return self

    def to_flat(self) -> dict[str, Any]:
        """Flatten to a Parquet row for the app (explanation kept as JSON)."""
        row = self.model_dump(
            mode="json",
            exclude={"explanation", "provenance", "contributing_sources"},
        )
        row["entity_key"] = self.entity_key
        row["alert_level"] = str(self.alert_level)
        row["contributing_sources"] = ";".join(self.contributing_sources)
        row["explanation_headline"] = self.explanation.headline
        row["explanation_narrative"] = self.explanation.narrative
        row["explanation_method"] = self.explanation.method
        return row
