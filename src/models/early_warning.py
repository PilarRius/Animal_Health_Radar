r"""Early warning: P(this country x disease becomes officially visible soon).

The question, stated precisely
------------------------------
For a country-disease pair at knowledge cut-off :math:`T`, the model estimates

.. math::

    \Pr\!\left[\,\text{official burden published in } (T,\, T+H]
        \;\ge\; \max\!\left(1,\; \phi \cdot \hat{r}_T \cdot \tfrac{H}{7}\right)\right]

with :math:`H` = ``early_warning.label_horizon_days`` and :math:`\hat r_T` the
currently visible weekly run-rate (see
:func:`~src.features.build.build_early_warning_labels`). For a quiet entity the
threshold collapses to 1 and the target means *emergence*; for one already
reporting it means *escalation*. That is one coherent target which is
non-trivial in both regimes, so the model is never asked to extrapolate into a
feature region it has no examples of.

Note what the target is **not**: it is not "an outbreak occurs". It is "the
official record changes". Those differ by exactly the reporting process the
nowcast models, and conflating them is the single most common way an
early-warning system ends up predicting administrative behaviour while claiming
to predict epidemiology. The distinction is stated on every screen that shows
this probability.

Temporal discipline
-------------------
Three windows, split by ``as_of`` and never shuffled:

==================  ==========================================  ==================
Window              Range                                       Used for
==================  ==========================================  ==================
train               ``as_of <= early_warning.train_end``        fitting the classifier
calibration         ``train_end < as_of <= calibration_end``    fitting the calibrator
test                ``as_of > calibration_end``                 reporting metrics
==================  ==========================================  ==================

Rows whose label horizon extends past the end of the corpus are dropped
(``label_observable == False``): there, "nothing was reported" is
indistinguishable from "we have no data yet", and training on that teaches the
model that the end of the dataset is peaceful.

Baseline values used by the explanation layer (feature medians, feature
quantiles) are computed on the **training** window only, so nothing about the
test period leaks into how an alert is explained.

Explanations
------------
Contributions are always a *computed model response*, never a narrative:

``shap``
    Exact tree SHAP values when :mod:`shap` is installed. Additive on the
    log-odds scale.
``occlusion``
    Otherwise: :math:`\Delta_j = f(x) - f(x \mid x_j := \text{median}_j)`, a
    genuine re-evaluation of the fitted model with one feature returned to its
    training-median value. Not exactly additive, but every number is a real
    model output and the method is identical in kind to the family-level
    counterfactual, which keeps the two panels of the UI consistent.
``coefficient``
    For the logistic variant: :math:`\beta_j (z_j - \bar z_j)`, exactly additive.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.features.build import FEATURE_FAMILIES, MODEL_FEATURES, features_in_family
from src.models.calibration import (
    CalibrationReport,
    classification_metrics,
    fit_calibrator,
    precision_at_k,
    reliability_table,
)
from src.schemas.enums import SignalFamily
from src.schemas.outputs import CounterfactualAblation, EvidenceContribution
from src.utils.config import AppConfig, get_config
from src.utils.dates import ensure_date
from src.utils.logging_utils import get_logger
from src.utils.stats import logit

LOGGER = get_logger(__name__)

try:  # optional: upgrades the explanation layer when available
    import shap  # type: ignore

    _SHAP_AVAILABLE = True
except Exception:  # pragma: no cover - absence is the normal case here
    shap = None  # type: ignore
    _SHAP_AVAILABLE = False

__all__ = ["EarlyWarningModel", "TemporalSplit", "SPLIT_NAMES"]

SPLIT_NAMES: tuple[str, ...] = ("train", "calibration", "test")

#: Human-readable glosses used in the "why this alert" panel. Descriptive only:
#: the numbers beside them are always model output.
FEATURE_DESCRIPTIONS: dict[str, str] = {
    "obs_ewma_z": "Own reported series vs its own recent level (control chart)",
    "obs_last_1w": "Outbreaks officially visible for the current week",
    "obs_last_4w": "Outbreaks officially visible in the last 4 weeks",
    "obs_last_13w": "Outbreaks officially visible in the last 13 weeks",
    "obs_weeks_since_last": "Weeks since the last official notification",
    "obs_log_growth_4w": "Growth of the visible series over the last 4 weeks",
    "obs_is_currently_reporting": "Currently has an open reporting stream",
    "spa_neighbour_activity_4w": "Reported activity in neighbouring countries (4 weeks)",
    "spa_neighbour_active_share": "Share of the neighbourhood currently reporting",
    "spa_nearest_active_km": "Distance to the nearest reporting country",
    "spa_border_pressure": "Number of land-bordering countries reporting",
    "hist_seasonal_baseline": "Seasonal norm for this country and week of year",
    "hist_excess_over_baseline": "Excess of the recent level over the seasonal norm",
    "hist_ever_reported": "Has ever reported this disease",
    "env_suitability": "Environmental suitability for this pathogen",
    "env_suitability_4w": "Environmental suitability, 4-week mean",
    "env_cold_snap_index": "Cold anomaly (drives waterfowl movement)",
    "env_temp_anomaly_c": "Temperature anomaly vs the local normal",
    "exp_host_density_log": "Density of the susceptible host population",
    "exp_national_stock_log": "National herd/flock size",
    "intel_fused_anomaly": "Fused media and aggregator anomaly (redundancy-discounted)",
    "intel_effective_sources": "Effective number of independent sources speaking",
    "intel_corroborating_sources": "Sources reporting above their own baseline",
    "gdelt_abnormal_volume": "GDELT news-volume anomaly",
    "padiweb_abnormal_volume": "PADI-web article-volume anomaly",
    "beacon_abnormal_volume": "BEACON signal-volume anomaly",
    "healthmap_abnormal_volume": "HealthMap alert-volume anomaly",
    "promed_confidence_weighted": "ProMED posts weighted by confidence",
    "eios_abnormal_volume": "EIOS board-item anomaly",
    "rep_reporting_probability": "Share of the current week expected to be visible already",
    "rep_expected_delay_days": "Expected onset-to-notification delay",
    "rep_delay_p90_days": "90th percentile notification delay",
}


@dataclass(frozen=True)
class TemporalSplit:
    """The one split policy the whole system uses. No shuffling, ever."""

    train_end: date
    calibration_end: date

    def assign(self, as_of: pd.Series) -> pd.Series:
        stamps = pd.to_datetime(as_of)
        out = pd.Series("test", index=stamps.index, dtype=object)
        out.loc[stamps <= pd.Timestamp(self.calibration_end)] = "calibration"
        out.loc[stamps <= pd.Timestamp(self.train_end)] = "train"
        return out

    def to_dict(self) -> dict[str, str]:
        return {
            "train_end": self.train_end.isoformat(),
            "calibration_end": self.calibration_end.isoformat(),
            "policy": "chronological; no shuffling, no random k-fold, no overlap",
        }


class EarlyWarningModel:
    """Calibrated classifier for imminent official visibility, with explanations."""

    version = "early_warning_v1"

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        primary_model: str | None = None,
        features: Sequence[str] | None = None,
    ) -> None:
        self.config = config or get_config()
        self.features: list[str] = list(features or MODEL_FEATURES)
        self.primary_model = str(
            primary_model or self.config.get("early_warning.primary_model", "gradient_boosting")
        )
        self.calibration_method = str(
            self.config.get("early_warning.calibration_method", "isotonic")
        )
        self.label_horizon_days = int(self.config.get("early_warning.label_horizon_days", 28))
        self.split = TemporalSplit(
            train_end=ensure_date(self.config.get("early_warning.train_end", "2023-12-31")),  # type: ignore[arg-type]
            calibration_end=ensure_date(
                self.config.get("early_warning.calibration_end", "2024-12-31")
            ),  # type: ignore[arg-type]
        )
        self._seed = int(self.config.random_seed)

        self.estimator: Any = None
        self.calibrator: Any = None
        self.baseline_: pd.Series = pd.Series(dtype=float)
        self.quantile_grid_: dict[str, np.ndarray] = {}
        self.reports_: dict[str, CalibrationReport] = {}
        self.split_sizes_: dict[str, dict[str, float]] = {}
        self.fitted_ = False
        self._explainer: Any = None
        self.explanation_method = "occlusion"

    # ------------------------------------------------------------------ #
    # data preparation
    # ------------------------------------------------------------------ #
    def build_training_frame(
        self, design: pd.DataFrame, labels: pd.DataFrame
    ) -> pd.DataFrame:
        """Join design matrix and labels, keep only rows with an observable label."""
        left = design.copy()
        left["as_of"] = pd.to_datetime(left["as_of"])
        right = labels.copy()
        right["as_of"] = pd.to_datetime(right["as_of"])

        frame = left.merge(right, on=["entity_key", "as_of"], how="inner")
        before = len(frame)
        frame = frame.loc[frame["label_observable"].astype(bool)].copy()
        LOGGER.info(
            "Early-warning frame: %s rows (%s dropped: label horizon beyond the corpus)",
            len(frame), before - len(frame),
        )
        frame["split"] = self.split.assign(frame["as_of"])
        return frame.sort_values(["as_of", "entity_key"]).reset_index(drop=True)

    def matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Design matrix in the frozen feature order, NaN/inf-free."""
        out = frame.reindex(columns=self.features).astype(float)
        return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # ------------------------------------------------------------------ #
    # fitting
    # ------------------------------------------------------------------ #
    def _make_estimator(self) -> Any:
        if self.primary_model == "logistic":
            return Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("model", LogisticRegression(C=0.5, max_iter=3000, solver="lbfgs")),
                ]
            )
        # Shallow trees and a slow learning rate: the panel is 40 entities wide
        # and highly autocorrelated, so capacity buys memorisation, not skill.
        return GradientBoostingClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=3,
            min_samples_leaf=25,
            subsample=0.9,
            random_state=self._seed,
        )

    def fit(self, design: pd.DataFrame, labels: pd.DataFrame) -> EarlyWarningModel:
        frame = self.build_training_frame(design, labels)
        if frame.empty:
            raise ValueError("Early-warning training frame is empty.")

        train = frame.loc[frame["split"] == "train"]
        calibration = frame.loc[frame["split"] == "calibration"]
        test = frame.loc[frame["split"] == "test"]

        if train.empty:
            raise ValueError(
                f"No training rows at or before early_warning.train_end="
                f"{self.split.train_end}. Widen time.training_as_of in config/config.yaml."
            )
        y_train = train["label"].to_numpy(dtype=int)
        if y_train.sum() == 0 or y_train.sum() == y_train.size:
            raise ValueError("Training labels are degenerate (all one class).")

        X_train = self.matrix(train)
        self.estimator = self._make_estimator()
        self.estimator.fit(X_train, y_train)
        # Estimator is ready; allow _raw_probability during calibration fitting.
        self.fitted_ = True

        # Baselines for explanation and ablation: training window only.
        self.baseline_ = X_train.median(numeric_only=True)
        self.quantile_grid_ = {
            feature: np.quantile(X_train[feature].to_numpy(dtype=float), np.linspace(0, 1, 101))
            for feature in self.features
        }

        # Calibration on the window the classifier never saw.
        if calibration.empty:
            LOGGER.warning(
                "No calibration rows in (%s, %s]; probabilities will be raw model output.",
                self.split.train_end, self.split.calibration_end,
            )
            self.calibrator = fit_calibrator("none", np.zeros(0), np.zeros(0))
        else:
            raw = self._raw_probability(self.matrix(calibration))
            self.calibrator = fit_calibrator(
                self.calibration_method, raw, calibration["label"].to_numpy(dtype=float)
            )

        self._setup_explainer(X_train)

        for name, block in (("train", train), ("calibration", calibration), ("test", test)):
            self.reports_[name] = self._evaluate_split(name, block)
            self.split_sizes_[name] = {
                "n": float(len(block)),
                "n_positive": float(block["label"].sum()) if len(block) else 0.0,
                "as_of_first": str(block["as_of"].min().date()) if len(block) else "",
                "as_of_last": str(block["as_of"].max().date()) if len(block) else "",
            }

        LOGGER.info(
            "EarlyWarningModel(%s) fitted | train n=%s (%s pos) | test PR-AUC=%s ECE=%s",
            self.primary_model, len(train), int(y_train.sum()),
            _fmt(self.reports_["test"].metrics.get("pr_auc")),
            _fmt(self.reports_["test"].metrics.get("ece")),
        )
        return self

    def _evaluate_split(self, name: str, block: pd.DataFrame) -> CalibrationReport:
        if block.empty:
            return CalibrationReport(split=name, n=0, n_positive=0, base_rate=float("nan"))
        y = block["label"].to_numpy(dtype=float)
        p = self.predict_proba(self.matrix(block))
        metrics = classification_metrics(y, p)
        metrics["precision_at_10"] = precision_at_k(y, p, 10)
        metrics["precision_at_20"] = precision_at_k(y, p, 20)
        return CalibrationReport(
            split=name,
            n=int(len(block)),
            n_positive=int(y.sum()),
            base_rate=float(y.mean()),
            metrics=metrics,
            reliability=reliability_table(y, p),
        )

    # ------------------------------------------------------------------ #
    # scoring
    # ------------------------------------------------------------------ #
    def _require_fitted(self) -> None:
        if not self.fitted_:
            raise RuntimeError("EarlyWarningModel used before fit().")

    def _raw_probability(self, X: pd.DataFrame) -> np.ndarray:
        """Uncalibrated P(label=1) from the estimator."""
        self._require_fitted()
        return np.clip(self.estimator.predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Uncalibrated score on the log-odds scale (the additive scale)."""
        self._require_fitted()
        if hasattr(self.estimator, "decision_function"):
            return np.asarray(self.estimator.decision_function(X), dtype=float)
        return logit(self._raw_probability(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Calibrated probability. This is the only number the UI may display."""
        return np.clip(self.calibrator.transform(self._raw_probability(X)), 0.0, 1.0)

    # ------------------------------------------------------------------ #
    # explanations
    # ------------------------------------------------------------------ #
    def _setup_explainer(self, X_train: pd.DataFrame) -> None:
        if self.primary_model == "logistic":
            self.explanation_method = "coefficient"
            return
        if _SHAP_AVAILABLE:
            try:
                self._explainer = shap.TreeExplainer(self.estimator)
                self.explanation_method = "shap"
                LOGGER.info("Explanation layer: exact tree SHAP values.")
                return
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("SHAP unavailable for this estimator (%s); using occlusion.", exc)
        self.explanation_method = "occlusion"
        LOGGER.info(
            "Explanation layer: occlusion (shap not installed). Contributions are "
            "re-evaluations of the fitted model with one feature at its training median."
        )

    def contributions(self, X: pd.DataFrame) -> pd.DataFrame:
        """``(n_rows, n_features)`` signed log-odds contributions.

        Whatever the method, the returned numbers are model evaluations. None
        of them is a hand-authored weight.
        """
        self._require_fitted()
        frame = self.matrix(X)

        if self.explanation_method == "coefficient":
            model: LogisticRegression = self.estimator.named_steps["model"]
            scaler: StandardScaler = self.estimator.named_steps["scale"]
            z = (frame.to_numpy(dtype=float) - scaler.mean_) / np.sqrt(scaler.var_ + 1e-12)
            z_baseline = (
                self.baseline_.reindex(self.features).to_numpy(dtype=float) - scaler.mean_
            ) / np.sqrt(scaler.var_ + 1e-12)
            values = model.coef_[0][None, :] * (z - z_baseline[None, :])
            return pd.DataFrame(values, columns=self.features, index=frame.index)

        if self.explanation_method == "shap" and self._explainer is not None:
            raw = self._explainer.shap_values(frame)
            values = np.asarray(raw[1] if isinstance(raw, list) else raw, dtype=float)
            if values.ndim == 3:  # (n, f, classes) in newer shap versions
                values = values[:, :, -1]
            return pd.DataFrame(values, columns=self.features, index=frame.index)

        # Occlusion: one model re-evaluation per feature.
        reference = self.score(frame)
        baseline = self.baseline_.reindex(self.features)
        deltas = np.zeros((len(frame), len(self.features)), dtype=float)
        for j, feature in enumerate(self.features):
            perturbed = frame.copy()
            perturbed[feature] = float(baseline.get(feature, 0.0))
            deltas[:, j] = reference - self.score(perturbed)
        return pd.DataFrame(deltas, columns=self.features, index=frame.index)

    def percentile_of(self, feature: str, value: float) -> float | None:
        """Where *value* sits in the training distribution of *feature*."""
        grid = self.quantile_grid_.get(feature)
        if grid is None or not np.isfinite(value):
            return None
        return float(np.clip(np.searchsorted(grid, value) / 100.0, 0.0, 1.0))

    def evidence_contributions(
        self, row: pd.Series, contributions: pd.Series, *, top_k: int = 6
    ) -> list[EvidenceContribution]:
        """The ``top_k`` strongest contributions for one row, as schema objects."""
        ordered = contributions.reindex(self.features).astype(float)
        ordered = ordered.loc[ordered.abs().sort_values(ascending=False).index][:top_k]
        out: list[EvidenceContribution] = []
        for feature, contribution in ordered.items():
            value = float(row.get(feature, np.nan))
            out.append(
                EvidenceContribution(
                    feature=str(feature),
                    family=FEATURE_FAMILIES.get(str(feature), SignalFamily.TEMPORAL_ANOMALY),
                    value=None if not np.isfinite(value) else value,
                    contribution=float(contribution),
                    percentile=self.percentile_of(str(feature), value),
                    description=FEATURE_DESCRIPTIONS.get(str(feature)),
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # counterfactual ablation by evidence family
    # ------------------------------------------------------------------ #
    def ablate_families(
        self, X: pd.DataFrame, *, families: Sequence[SignalFamily] | None = None
    ) -> dict[SignalFamily, np.ndarray]:
        """Calibrated probability with each evidence family neutralised.

        "Neutralised" means every feature in the family is set to its
        **training-median** value and the fitted model is re-run. This is a real
        counterfactual evaluation of the model, not an attribution heuristic: it
        answers "what would this alert look like if we had never seen the media
        signals?" in the only way that can be checked.
        """
        self._require_fitted()
        frame = self.matrix(X)
        baseline = self.baseline_.reindex(self.features)
        pool = list(families) if families is not None else list(SignalFamily)
        out: dict[SignalFamily, np.ndarray] = {}
        for family in pool:
            members = features_in_family(family, among=self.features)
            if not members:
                continue
            perturbed = frame.copy()
            for feature in members:
                perturbed[feature] = float(baseline.get(feature, 0.0))
            out[family] = self.predict_proba(perturbed)
        return out

    def counterfactuals_for_row(
        self, X: pd.DataFrame, index: int, probability_with: float
    ) -> list[CounterfactualAblation]:
        """Family ablations for a single row, as schema objects."""
        ablated = self.ablate_families(X.iloc[[index]])
        out: list[CounterfactualAblation] = []
        for family, probabilities in ablated.items():
            out.append(
                CounterfactualAblation(
                    family=family,
                    n_features_ablated=len(features_in_family(family, among=self.features)),
                    probability_with=float(np.clip(probability_with, 0.0, 1.0)),
                    probability_without=float(np.clip(probabilities[0], 0.0, 1.0)),
                )
            )
        return sorted(out, key=lambda c: abs(c.delta), reverse=True)

    # ------------------------------------------------------------------ #
    # reporting
    # ------------------------------------------------------------------ #
    def feature_importance(self) -> pd.DataFrame:
        """Global importance, with each feature's evidence family attached."""
        self._require_fitted()
        if self.primary_model == "logistic":
            model: LogisticRegression = self.estimator.named_steps["model"]
            values = np.abs(model.coef_[0])
            kind = "abs_standardised_coefficient"
        else:
            values = np.asarray(self.estimator.feature_importances_, dtype=float)
            kind = "impurity_reduction"
        return (
            pd.DataFrame(
                {
                    "feature": self.features,
                    "importance": values,
                    "family": [str(FEATURE_FAMILIES.get(f, "unknown")) for f in self.features],
                    "importance_type": kind,
                }
            )
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )

    def family_importance(self) -> pd.DataFrame:
        """Importance aggregated to the evidence families used for ablation."""
        return (
            self.feature_importance()
            .groupby("family", as_index=False)
            .agg(importance=("importance", "sum"), n_features=("feature", "size"))
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )

    def metrics_frame(self) -> pd.DataFrame:
        return pd.DataFrame([report.to_dict() for report in self.reports_.values()])

    def reliability_frame(self) -> pd.DataFrame:
        frames = []
        for name, report in self.reports_.items():
            if report.reliability.empty:
                continue
            block = report.reliability.copy()
            block.insert(0, "split", name)
            frames.append(block)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def describe(self) -> dict[str, Any]:
        return {
            "model": "EarlyWarningModel",
            "version": self.version,
            "estimator": self.primary_model,
            "target": (
                "P(official burden published in the next "
                f"{self.label_horizon_days} days reaches the emergence/escalation threshold). "
                "This is a statement about the OFFICIAL RECORD, not about disease occurrence."
            ),
            "n_features": len(self.features),
            "feature_families": sorted({str(v) for v in FEATURE_FAMILIES.values()}),
            "split": self.split.to_dict(),
            "split_sizes": self.split_sizes_,
            "calibration": {
                "requested_method": self.calibration_method,
                **(self.calibrator.describe() if self.calibrator is not None else {}),
                "fitted_on": "calibration window only (never the training window)",
            },
            "explanation_method": self.explanation_method,
            "shap_available": _SHAP_AVAILABLE,
            "metrics": {name: report.to_dict() for name, report in self.reports_.items()},
            "top_features": self.feature_importance().head(15).to_dict(orient="records")
            if self.fitted_ else [],
            "known_limitations": [
                "Trained on a synthetic corpus: absolute probabilities are not transferable "
                "to real surveillance data without refitting.",
                "The target is official visibility, which is a joint function of disease "
                "activity and reporting behaviour.",
                "Country-disease panel of 40 entities: effective sample size is far smaller "
                "than the row count because rows are autocorrelated in time.",
            ],
        }


def _fmt(value: float | None) -> str:
    if value is None or not np.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.3f}"
