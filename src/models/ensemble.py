r"""Combining models without hiding which one did the work.

Two combination problems appear in this system and they have different shapes.

**Probabilistic count forecasts** (:func:`crps_weights`). The three forecast
members answer the same question with different inductive biases: a regression
on covariates, a damped extrapolation of the recent trajectory, and a seasonal
climatology. Which one is right depends on the regime -- the trend member wins
mid-epidemic, the climatology wins in the off-season, the GLM wins when the
covariates are informative. Rather than choosing, members are weighted by their
out-of-sample CRPS on a validation window that follows the training window in
time.

Weights are a softmax on the negative normalised CRPS:

.. math::

    w_m \;\propto\; \exp\!\left(-\frac{\text{CRPS}_m}{\tau\,\overline{\text{CRPS}}}\right)

The normalisation by the mean CRPS makes the temperature :math:`\tau`
scale-free, so the same setting behaves sensibly whether counts are in single
digits or hundreds. A floor (``forecast.min_weight``) keeps every member
alive: a member driven to zero weight stops being a check on the others, and in
a regime shift the currently-worst member is often the one that recovers first.

**Binary alert scores** (:class:`ScoreStacker`). Combining the fusion model
with the single-signal baselines is a different job: the inputs are on
incomparable scales and the target is binary. A rank-average is provided for
the scale-free case, and a logistic stacker fitted on a held-out window for
when the relative reliability of the inputs should itself be learned. Both are
fitted strictly after the members' own training window, so stacking cannot
launder in-sample skill into the ensemble.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src.utils.logging_utils import get_logger
from src.utils.stats import EPS, logit

LOGGER = get_logger(__name__)

__all__ = ["crps_weights", "equal_weights", "ScoreStacker", "rank_average"]


def equal_weights(members: Sequence[str]) -> dict[str, float]:
    if not members:
        return {}
    share = 1.0 / len(members)
    return {str(name): share for name in members}


def crps_weights(
    crps_by_member: Mapping[str, float],
    *,
    min_weight: float = 0.05,
    temperature: float = 0.5,
) -> dict[str, float]:
    """Softmax weights from validation CRPS (lower CRPS -> higher weight).

    Members with a non-finite CRPS (no scorable validation rows) are given the
    floor weight rather than being dropped, so the ensemble composition does
    not silently change between runs.
    """
    names = [str(name) for name in crps_by_member]
    if not names:
        return {}

    scores = np.array([float(crps_by_member[name]) for name in names], dtype=float)
    finite = np.isfinite(scores)
    if not finite.any():
        LOGGER.warning("No member produced a finite CRPS; falling back to equal weights.")
        return equal_weights(names)

    reference = float(np.mean(scores[finite]))
    scale = max(abs(reference) * float(temperature), EPS)
    raw = np.where(finite, np.exp(-(scores - np.min(scores[finite])) / scale), 0.0)
    if raw.sum() <= 0:
        return equal_weights(names)
    weights = raw / raw.sum()

    # Apply the floor, then renormalise the remainder proportionally.
    floor = float(np.clip(min_weight, 0.0, 1.0 / len(names)))
    weights = np.maximum(weights, floor)
    weights = weights / weights.sum()
    return {name: float(round(w, 6)) for name, w in zip(names, weights, strict=True)}


def rank_average(scores: Mapping[str, np.ndarray]) -> np.ndarray:
    """Average percentile rank across members: scale-free, no fitting."""
    if not scores:
        return np.zeros(0)
    stacked = []
    for values in scores.values():
        arr = np.asarray(values, dtype=float)
        order = np.argsort(np.argsort(np.nan_to_num(arr, nan=-np.inf), kind="mergesort"))
        stacked.append(order / max(arr.size - 1, 1))
    return np.mean(np.vstack(stacked), axis=0)


class ScoreStacker:
    """Logistic stacking of calibrated member probabilities on the logit scale.

    Fitted on a window that follows every member's own training window. The
    fitted coefficients are exposed so that the ensemble can be reported as
    "70% fusion model, 30% media anomaly" rather than as a black box.
    """

    def __init__(self, members: Sequence[str], *, C: float = 1.0) -> None:
        self.members = [str(name) for name in members]
        self._model = LogisticRegression(C=float(C), max_iter=2000, solver="lbfgs")
        self.fitted_ = False
        self.n_obs_ = 0

    def _matrix(self, probabilities: Mapping[str, np.ndarray]) -> np.ndarray:
        columns = []
        n = max((np.asarray(v).size for v in probabilities.values()), default=0)
        for name in self.members:
            values = np.asarray(probabilities.get(name, np.full(n, 0.5)), dtype=float)
            columns.append(logit(np.nan_to_num(values, nan=0.5)))
        return np.column_stack(columns) if columns else np.zeros((n, 0))

    def fit(self, probabilities: Mapping[str, np.ndarray], y: np.ndarray) -> ScoreStacker:
        X = self._matrix(probabilities)
        target = np.asarray(y, dtype=int)
        self.n_obs_ = int(target.size)
        if X.shape[1] and target.size and 0 < target.sum() < target.size:
            self._model.fit(X, target)
            self.fitted_ = True
        else:
            LOGGER.warning("ScoreStacker not fitted: degenerate target or no members.")
        return self

    def predict_proba(self, probabilities: Mapping[str, np.ndarray]) -> np.ndarray:
        X = self._matrix(probabilities)
        if not self.fitted_:
            return np.clip(np.mean(np.asarray(list(probabilities.values()), dtype=float), axis=0), 0, 1)
        return self._model.predict_proba(X)[:, 1]

    def weights(self) -> pd.DataFrame:
        """Standardised contribution of each member, as a readable table."""
        if not self.fitted_:
            return pd.DataFrame(columns=["member", "coefficient", "share"])
        coefficients = self._model.coef_[0]
        magnitude = np.abs(coefficients)
        total = magnitude.sum()
        return pd.DataFrame(
            {
                "member": self.members,
                "coefficient": coefficients,
                "share": magnitude / total if total > 0 else np.zeros_like(magnitude),
            }
        ).sort_values("share", ascending=False).reset_index(drop=True)
