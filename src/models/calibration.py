"""Probability calibration without temporal leakage.

Calibrators are always fitted on a window the classifier has not seen
(``early_warning.calibration_end``). Metrics helpers used by EarlyWarningModel
live here so evaluation and fitting share one definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

from src.utils.stats import expected_calibration_error

__all__ = [
    "Calibrator",
    "CalibrationReport",
    "calibration_report",
    "classification_metrics",
    "fit_calibrator",
    "precision_at_k",
    "reliability_table",
]

Method = Literal["isotonic", "platt", "none"]


@dataclass
class Calibrator:
    method: Method = "isotonic"
    _iso: IsotonicRegression | None = None
    _platt: LogisticRegression | None = None

    def fit(self, scores: np.ndarray, y: np.ndarray) -> Calibrator:
        scores = np.asarray(scores, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        if self.method == "none" or len(scores) == 0 or len(np.unique(y)) < 2:
            return self
        if self.method == "isotonic":
            self._iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            self._iso.fit(scores, y)
        else:
            self._platt = LogisticRegression(max_iter=800)
            self._platt.fit(scores.reshape(-1, 1), y.astype(int))
        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        scores = np.asarray(scores, dtype=float).ravel()
        if self.method == "none":
            return np.clip(scores, 0.0, 1.0)
        if self.method == "isotonic" and self._iso is not None:
            return np.clip(self._iso.predict(scores), 0.0, 1.0)
        if self.method == "platt" and self._platt is not None:
            return self._platt.predict_proba(scores.reshape(-1, 1))[:, 1]
        return np.clip(scores, 0.0, 1.0)

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "fitted": self._iso is not None or self._platt is not None or self.method == "none",
        }


def fit_calibrator(method: str, scores: np.ndarray, y: np.ndarray) -> Calibrator:
    """Factory used by EarlyWarningModel."""
    allowed: Method = method if method in ("isotonic", "platt", "none") else "isotonic"  # type: ignore[assignment]
    return Calibrator(method=allowed).fit(scores, y)


@dataclass
class CalibrationReport:
    split: str
    n: int
    n_positive: int
    base_rate: float
    metrics: dict[str, float] = field(default_factory=dict)
    reliability: Any = field(default_factory=lambda: __import__("pandas").DataFrame())

    def to_dict(self) -> dict[str, Any]:
        reliability = self.reliability
        if hasattr(reliability, "to_dict"):
            reliability_payload = reliability.to_dict(orient="records")
        else:
            reliability_payload = reliability
        return {
            "split": self.split,
            "n": self.n,
            "n_positive": self.n_positive,
            "base_rate": self.base_rate,
            "metrics": self.metrics,
            "reliability": reliability_payload,
        }


def classification_metrics(y_true: np.ndarray, p_hat: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=int).ravel()
    p_hat = np.clip(np.asarray(p_hat, dtype=float).ravel(), 1e-6, 1 - 1e-6)
    out: dict[str, float] = {
        "brier": float(brier_score_loss(y_true, p_hat)) if len(y_true) else float("nan"),
        "ece": float(expected_calibration_error(y_true, p_hat)) if len(y_true) else float("nan"),
    }
    if len(y_true) and len(np.unique(y_true)) > 1:
        out["roc_auc"] = float(roc_auc_score(y_true, p_hat))
        out["pr_auc"] = float(average_precision_score(y_true, p_hat))
    else:
        out["roc_auc"] = float("nan")
        out["pr_auc"] = float("nan")

    # Linear calibration slope / intercept of outcomes on probabilities
    if len(y_true) >= 5:
        x = np.column_stack([np.ones(len(p_hat)), p_hat])
        try:
            beta, _, _, _ = np.linalg.lstsq(x, y_true.astype(float), rcond=None)
            out["calibration_intercept"] = float(beta[0])
            out["calibration_slope"] = float(beta[1])
        except np.linalg.LinAlgError:
            out["calibration_intercept"] = float("nan")
            out["calibration_slope"] = float("nan")
    return out


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    y_true = np.asarray(y_true, dtype=int).ravel()
    scores = np.asarray(scores, dtype=float).ravel()
    if len(y_true) == 0 or k <= 0:
        return float("nan")
    k = min(int(k), len(y_true))
    order = np.argsort(-scores)[:k]
    return float(np.mean(y_true[order]))


def reliability_table(y_true: np.ndarray, p_hat: np.ndarray, n_bins: int = 10):
    import pandas as pd

    y_true = np.asarray(y_true, dtype=int).ravel()
    p_hat = np.clip(np.asarray(p_hat, dtype=float).ravel(), 0.0, 1.0)
    if len(y_true) < n_bins or len(np.unique(y_true)) < 2:
        return pd.DataFrame(columns=["mean_predicted", "fraction_positive", "count"])
    try:
        frac_pos, mean_pred = calibration_curve(y_true, p_hat, n_bins=n_bins, strategy="quantile")
    except ValueError:
        return pd.DataFrame(columns=["mean_predicted", "fraction_positive", "count"])
    return pd.DataFrame(
        {
            "mean_predicted": mean_pred,
            "fraction_positive": frac_pos,
            "count": np.nan,
        }
    )


def calibration_report(y_true: np.ndarray, p_hat: np.ndarray, n_bins: int = 10) -> dict[str, float]:
    """Back-compat dict form used by older call sites."""
    metrics = classification_metrics(y_true, p_hat)
    metrics["n"] = float(len(np.asarray(y_true).ravel()))
    return metrics
