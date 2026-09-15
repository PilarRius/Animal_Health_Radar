"""Alert construction from model outputs (thresholds are operational, not optimal)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.features.temporal import OfficialHistory
from src.models.early_warning import EarlyWarningModel
from src.models.forecast import ForecastModel
from src.models.nowcast import LatentStateNowcastModel
from src.schemas.enums import AlertLevel
from src.schemas.outputs import AlertObject, Explanation
from src.utils.config import get_config, load_countries, load_thresholds
from src.utils.dates import ensure_date
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["alert_level_from_probability", "build_alerts", "investigation_priority"]


def alert_level_from_probability(probability: float) -> AlertLevel:
    thr = load_thresholds().get("alert_levels", [])
    level = AlertLevel.NONE
    for band in thr:
        if probability >= float(band.get("min_probability", 0.0)):
            level = AlertLevel(str(band["level"]))
    return level


def investigation_priority(
    ew_prob: float,
    reporting_gap: float,
    latent: float,
    forecast_growth: float,
    intel: float,
) -> float:
    weights = (load_thresholds().get("investigation_priority") or {}).get("weights") or {
        "early_warning_probability": 0.34,
        "reporting_gap": 0.22,
        "latent_activity_norm": 0.20,
        "forecast_growth": 0.14,
        "intelligence_signal": 0.10,
    }
    latent_norm = float(1.0 - np.exp(-max(latent, 0.0) / 5.0))
    growth = float(np.clip(forecast_growth, 0.0, 1.0))
    intel_n = float(1.0 / (1.0 + np.exp(-intel)))
    score = (
        weights.get("early_warning_probability", 0.34) * ew_prob
        + weights.get("reporting_gap", 0.22) * reporting_gap
        + weights.get("latent_activity_norm", 0.20) * latent_norm
        + weights.get("forecast_growth", 0.14) * growth
        + weights.get("intelligence_signal", 0.10) * intel_n
    )
    return float(np.clip(score, 0.0, 1.0))


def _priority_band(score: float) -> str:
    bands = (load_thresholds().get("investigation_priority") or {}).get("bands") or {}
    order = ["very_high", "high", "moderate", "low"]
    thresholds = {k: float(v) for k, v in bands.items()}
    for name in order:
        if score >= thresholds.get(name, 1.0):
            return name
    return "low"


def _confidence_band(score: float) -> str:
    bands = (load_thresholds().get("evidence") or {}).get("confidence_bands") or {
        "low": 0.0, "moderate": 0.4, "high": 0.68
    }
    if score >= float(bands.get("high", 0.68)):
        return "high"
    if score >= float(bands.get("moderate", 0.4)):
        return "moderate"
    return "low"


def _build_explanation(ew_model: EarlyWarningModel, row: pd.Series, probability: float) -> Explanation:
    frame = pd.DataFrame([row])
    contrib_matrix = ew_model.contributions(frame)
    contrib_series = contrib_matrix.iloc[0]
    top = ew_model.evidence_contributions(row, contrib_series, top_k=8)
    counterfactuals = ew_model.counterfactuals_for_row(frame, 0, probability)
    bits = [
        f"{c.feature} (Δlogit={c.contribution:+.2f})"
        for c in top[:3]
    ]
    headline = (
        f"Model-indicated elevated official-visibility probability {probability:.0%}"
        if probability >= 0.4
        else f"Model-indicated early-warning probability {probability:.0%}"
    )
    narrative = (
        "Calibrated probability that officially visible activity will appear or "
        "intensify within the label horizon, given information available at as-of. "
        "Top contributions: "
        + ("; ".join(bits) if bits else "diffuse across families.")
        + " This is a MODEL ESTIMATE about the official record, not a confirmed outbreak."
    )
    return Explanation(
        headline=headline,
        narrative=narrative,
        top_contributions=top,
        counterfactuals=counterfactuals,
        method=str(ew_model.explanation_method),
        caveats=[
            "Target is official visibility / escalation, not latent confirmation.",
            "Synthetic corpus probabilities are not transferable without refitting.",
        ],
    )


def build_alerts(
    design: pd.DataFrame,
    ew_model: EarlyWarningModel,
    nowcast_model: LatentStateNowcastModel,
    forecast_model: ForecastModel,
    history: OfficialHistory,
    *,
    as_of_dates: list[date] | None = None,
    model_version: str = "0.1.0",
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Build predictions.parquet rows, alerts.parquet rows, and explanation JSON."""
    config = get_config()
    countries = load_countries()
    frame = design.copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"]).dt.date
    if as_of_dates is not None:
        frame = frame.loc[frame["as_of"].isin(set(as_of_dates))]

    # Score early warning in one vectorised pass
    probs = ew_model.predict_proba(ew_model.matrix(frame))
    scores = ew_model.score(ew_model.matrix(frame))
    frame = frame.copy()
    frame["early_warning_probability"] = probs
    frame["early_warning_score"] = scores

    unique_as_ofs = sorted(frame["as_of"].unique())
    nowcast_by_key: dict[tuple[str, date], Any] = {}
    forecast_by_key: dict[tuple[str, date, int], Any] = {}

    for as_of in unique_as_ofs:
        design_slice = frame.loc[frame["as_of"] == as_of].copy()
        objects = nowcast_model.nowcast(history, as_of, window_weeks=1)
        levels: dict[str, float] = {}
        for obj in objects:
            nowcast_by_key[(obj.entity_key, as_of)] = obj
            levels[obj.entity_key] = float(obj.latent_disease_estimate)

        fcasts = forecast_model.predict(
            as_of,
            history,
            design_slice,
            current_level=pd.Series(levels),
        )
        for fobj in fcasts:
            forecast_by_key[(fobj.entity_key, as_of, int(fobj.horizon_days))] = fobj

    pred_rows: list[dict[str, Any]] = []
    alert_rows: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []

    for _, row in frame.iterrows():
        as_of = ensure_date(row["as_of"])
        assert as_of is not None
        entity = str(row["entity_key"])
        country, disease = entity.split("|")
        ew_prob = float(row["early_warning_probability"])
        ew_score = float(row["early_warning_score"])

        nc = nowcast_by_key.get((entity, as_of))
        if nc is None:
            continue

        f7 = forecast_by_key.get((entity, as_of, 7))
        f14 = forecast_by_key.get((entity, as_of, 14))
        f28 = forecast_by_key.get((entity, as_of, 28))

        growth = 0.0
        if f14 is not None and nc.latent_disease_estimate > 0:
            growth = float(np.clip(f14.mean / max(nc.latent_disease_estimate, 1e-6) - 1.0, -1.0, 3.0))
            growth = float(1.0 / (1.0 + np.exp(-growth)))

        intel = float(row.get("intel_fused_anomaly", 0.0) or 0.0)
        priority = investigation_priority(
            ew_prob, nc.reporting_gap, nc.latent_disease_estimate, growth, intel
        )
        level = alert_level_from_probability(ew_prob)
        explain = _build_explanation(ew_model, row, ew_prob)
        alert_id = f"AHR-{country}-{disease}-{as_of.isoformat()}"

        alert = AlertObject(
            alert_id=alert_id,
            country_iso3=country,
            country_name=countries[country].name if country in countries else None,
            disease=disease,
            as_of=as_of,
            generated_at=datetime.utcnow().replace(microsecond=0),
            early_warning_score=ew_score,
            early_warning_probability=ew_prob,
            label_horizon_days=int(config.get("early_warning.label_horizon_days", 28)),
            alert_level=level,
            latent_disease_estimate=nc.latent_disease_estimate,
            observed_disease_burden=nc.observed_disease_burden,
            estimated_hidden_burden=nc.estimated_hidden_burden,
            reporting_gap=nc.reporting_gap,
            nowcast_lower=nc.nowcast_lower,
            nowcast_upper=nc.nowcast_upper,
            reporting_probability=nc.reporting_probability,
            expected_reporting_delay=nc.expected_reporting_delay,
            forecast_7d=f7.point if f7 else None,
            forecast_7d_lower=f7.lower if f7 else None,
            forecast_7d_upper=f7.upper if f7 else None,
            forecast_14d=f14.point if f14 else None,
            forecast_14d_lower=f14.lower if f14 else None,
            forecast_14d_upper=f14.upper if f14 else None,
            forecast_28d=f28.point if f28 else None,
            forecast_28d_lower=f28.lower if f28 else None,
            forecast_28d_upper=f28.upper if f28 else None,
            p_exceed_14d=f14.p_exceed_threshold if f14 else None,
            p_increase_14d=f14.p_increase if f14 else None,
            p_new_outbreak_28d=f28.p_new_outbreak if f28 else None,
            temporal_anomaly=float(row.get("obs_ewma_z", 0.0) or 0.0),
            spatial_risk=float(row.get("spa_neighbour_activity_4w", 0.0) or 0.0),
            environmental_signal=float(row.get("env_suitability", 0.0) or 0.0),
            livestock_exposure=float(row.get("exp_host_density_log", 0.0) or 0.0),
            intelligence_signal=intel,
            historical_baseline=float(row.get("hist_seasonal_baseline", 0.0) or 0.0),
            confidence=nc.confidence,
            confidence_band=_confidence_band(nc.confidence),
            evidence_independence=float(row.get("intel_effective_sources", 1.0) or 1.0),
            contributing_sources=[],
            n_records_used=nc.n_contributing_records,
            investigation_priority=priority,
            priority_band=_priority_band(priority),
            explanation=explain,
            provenance=[],
            recommended_action=None,
            data_realism=str(config.data_mode),
        )
        flat = alert.to_flat()
        flat["model_version"] = model_version
        alert_rows.append(flat)

        pred_rows.append(
            {
                "as_of_date": as_of.isoformat(),
                "country": country,
                "admin1": None,
                "disease": disease,
                "entity_key": entity,
                "early_warning_probability": ew_prob,
                "alert_level": str(level),
                "latent_mean": nc.latent_disease_estimate,
                "latent_lower": nc.nowcast_lower,
                "latent_upper": nc.nowcast_upper,
                "observed": nc.observed_disease_burden,
                "reporting_gap": nc.reporting_gap,
                "reporting_probability": nc.reporting_probability,
                "expected_delay": nc.expected_reporting_delay,
                "forecast_7d": f7.point if f7 else None,
                "forecast_7d_lower": f7.lower if f7 else None,
                "forecast_7d_upper": f7.upper if f7 else None,
                "forecast_14d": f14.point if f14 else None,
                "forecast_14d_lower": f14.lower if f14 else None,
                "forecast_14d_upper": f14.upper if f14 else None,
                "forecast_28d": f28.point if f28 else None,
                "forecast_28d_lower": f28.lower if f28 else None,
                "forecast_28d_upper": f28.upper if f28 else None,
                "confidence": nc.confidence,
                "investigation_priority": priority,
                "temporal_anomaly": float(row.get("obs_ewma_z", 0.0) or 0.0),
                "spatial_risk": float(row.get("spa_neighbour_activity_4w", 0.0) or 0.0),
                "environmental_signal": float(row.get("env_suitability", 0.0) or 0.0),
                "livestock_exposure": float(row.get("exp_host_density_log", 0.0) or 0.0),
                "intelligence_signal": intel,
                "historical_baseline": float(row.get("hist_seasonal_baseline", 0.0) or 0.0),
                "model_version": model_version,
            }
        )
        explanations.append(
            {
                "alert_id": alert_id,
                "entity_key": entity,
                "as_of": as_of.isoformat(),
                "explanation": explain.model_dump(mode="json"),
            }
        )

    LOGGER.info("Built %s alert objects across %s prediction rows", len(alert_rows), len(pred_rows))
    return pd.DataFrame(pred_rows), pd.DataFrame(alert_rows), explanations
