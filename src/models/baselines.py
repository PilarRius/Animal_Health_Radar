"""Baselines: the models the system has to beat to justify its existence.

A gradient-boosted fusion of forty features is only interesting if it
outperforms the things a competent epidemiologist would do with a spreadsheet.
This module implements those things properly rather than as strawmen:

:class:`SeasonalBaseline`
    Week-of-year climatology of the officially reported series, built from the
    *vintage visible at as_of* and from prior calendar years only. This is the
    "what is normal for here, now" reference used by the excess statistic and
    as a forecast ensemble member.

:class:`EWMAAnomalyDetector`
    Exponentially weighted control chart. The standard aberration-detection
    tool in public-health surveillance (the Farrington/EARS family of methods
    are refinements of the same idea). Strictly causal: the statistic at time
    *t* is compared with a level and variance estimated from *t-1* backwards.

:class:`CUSUMDetector`
    Page's cumulative sum. Complementary to the EWMA: it accumulates small
    persistent departures that never individually cross a z-threshold, which is
    the actual signature of a slow front-wave epidemic like ASF in wild boar.

:class:`CountGLM`
    Poisson / negative-binomial log-link regression fitted by iteratively
    reweighted least squares with a ridge penalty. Used as the regression
    baseline for counts and as the ``negbin_glm`` member of the forecast
    ensemble. Written directly on numpy/scipy so the project does not depend on
    statsmodels, and so the likelihood being maximised is visible in the code.

:data:`EARLY_WARNING_BASELINES`
    Single-signal heuristic scorers (EWMA only, seasonal excess only, media
    only, neighbours only). Their scores are calibrated on the same window and
    scored with the same metrics as the fusion model, so the comparison in
    ``reports/validation/`` is apples to apples.

:class:`OfficialRecordOnlyBaseline`
    A *fitted* logistic regression restricted to features derived from the
    official record. This is the honest "surveillance as usual" competitor: it
    knows everything WAHIS knows and nothing else. The value added by
    environmental, exposure and intelligence evidence is measured against it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.features.baseline import BASELINE_FEATURES
from src.features.temporal import TEMPORAL_FEATURES, OfficialHistory
from src.utils.dates import DateLike, ensure_date, iso_week_start
from src.utils.logging_utils import get_logger
from src.utils.stats import EPS, fit_nb_dispersion, nb_quantile, nb_rvs, robust_z, safe_log

LOGGER = get_logger(__name__)

__all__ = [
    "SeasonalBaseline",
    "EWMAAnomalyDetector",
    "CUSUMDetector",
    "CountGLM",
    "HeuristicBaseline",
    "EARLY_WARNING_BASELINES",
    "OfficialRecordOnlyBaseline",
    "OFFICIAL_ONLY_FEATURES",
]


# --------------------------------------------------------------------------- #
# seasonal climatology
# --------------------------------------------------------------------------- #
class SeasonalBaseline:
    """Vintage-correct week-of-year climatology of the reported series.

    The estimate for ISO week *w* of the current year is the mean reported
    count over weeks within ``+/- week_window`` of *w* in **previous calendar
    years**, using only reports that had been published by ``as_of``. Two
    consequences are deliberate:

    * the baseline for a week never contains that week, so "excess over
      baseline" is not partly self-referential;
    * a country whose last-December reports arrived in March has a weaker
      December baseline at a February as-of date than it will have in April.
      That is not a bug: it is what was actually known.
    """

    def __init__(self, *, week_window: int = 2, min_years: int = 1) -> None:
        self.week_window = int(week_window)
        self.min_years = int(min_years)

    def expected(
        self,
        history: OfficialHistory,
        as_of: DateLike,
        target_week: DateLike,
    ) -> np.ndarray:
        """Expected reported count for *target_week*, per entity, at *as_of*."""
        as_of_date = ensure_date(as_of)
        target = iso_week_start(target_week)
        w_now = history.week_position(iso_week_start(as_of_date))
        counts = history.counts_as_of(as_of_date)[:, : w_now + 1]
        weeks = history.weeks[: w_now + 1]
        if counts.shape[1] == 0:
            return np.zeros(history.n_entities)

        iso_weeks = np.array([w.isocalendar().week for w in weeks], dtype=int)
        years = np.array([w.isocalendar().year for w in weeks], dtype=int)
        target_iso = target.isocalendar().week
        target_year = target.isocalendar().year

        # Circular distance on the ISO week axis; strictly earlier years only.
        distance = np.minimum(
            np.abs(iso_weeks - target_iso), 53 - np.abs(iso_weeks - target_iso)
        )
        window = (distance <= self.week_window) & (years < target_year)
        if not window.any():
            # No prior year available: fall back to the trailing 8-week level,
            # which is a level estimate rather than a seasonal one. Flagged by
            # `years_available == 0`.
            return counts[:, -8:].mean(axis=1)
        return counts[:, window].mean(axis=1)

    def years_available(
        self, history: OfficialHistory, as_of: DateLike, target_week: DateLike
    ) -> int:
        as_of_date = ensure_date(as_of)
        target = iso_week_start(target_week)
        w_now = history.week_position(iso_week_start(as_of_date))
        weeks = history.weeks[: w_now + 1]
        years = {w.isocalendar().year for w in weeks if w.isocalendar().year < target.isocalendar().year}
        return len(years)


# --------------------------------------------------------------------------- #
# control charts
# --------------------------------------------------------------------------- #
@dataclass
class EWMAAnomalyDetector:
    """Causal EWMA control chart on the variance-stabilised reported series.

    ``alpha`` is the smoothing weight, ``threshold`` the z-score at which an
    aberration is declared. Counts are passed through ``log(1 + y)`` first:
    weekly outbreak counts are heavily skewed and an untransformed chart
    triggers on Poisson noise in high-incidence countries while missing real
    departures in low-incidence ones.
    """

    alpha: float = 0.30
    threshold: float = 2.0
    min_sd: float = 0.5

    def score(self, series: Sequence[float] | np.ndarray) -> np.ndarray:
        """Per-time-step z-scores. Element *t* uses only data up to *t*."""
        y = safe_log(np.asarray(series, dtype=float))
        n = y.size
        z = np.zeros(n, dtype=float)
        if n == 0:
            return z
        level = float(y[0])
        var = max(float(np.var(y[: min(8, n)])), self.min_sd**2)
        for t in range(n):
            sd = max(np.sqrt(max(var, 0.0)), self.min_sd)
            z[t] = (y[t] - level) / sd
            residual = y[t] - level
            level = self.alpha * y[t] + (1.0 - self.alpha) * level
            var = self.alpha * residual**2 + (1.0 - self.alpha) * var
        return z

    def alarms(self, series: Sequence[float] | np.ndarray) -> np.ndarray:
        return (self.score(series) >= self.threshold).astype(int)

    def score_panel(self, counts: np.ndarray) -> np.ndarray:
        """Latest z-score for every row of an ``(entities, weeks)`` array."""
        if counts.size == 0:
            return np.zeros(counts.shape[0])
        return np.array([self.score(row)[-1] if row.size else 0.0 for row in counts])


@dataclass
class CUSUMDetector:
    """Page's one-sided upward CUSUM on standardised counts.

    .. math::

        S_t = \\max\\left(0,\\; S_{t-1} + z_t - k\\right)

    An alarm is raised when :math:`S_t > h`. The reference value *k* is the
    departure size (in standard deviations) the chart is tuned to ignore, so
    small persistent excesses accumulate rather than being smoothed away -- the
    reason this is kept alongside the EWMA rather than instead of it.
    """

    k: float = 0.5
    h: float = 3.0

    def score(self, series: Sequence[float] | np.ndarray) -> np.ndarray:
        y = safe_log(np.asarray(series, dtype=float))
        if y.size == 0:
            return np.zeros(0)
        z = robust_z(y)
        s = np.zeros(y.size, dtype=float)
        running = 0.0
        for t in range(y.size):
            running = max(0.0, running + float(z[t]) - self.k)
            s[t] = running
        return s

    def alarms(self, series: Sequence[float] | np.ndarray) -> np.ndarray:
        return (self.score(series) > self.h).astype(int)

    def score_panel(self, counts: np.ndarray) -> np.ndarray:
        if counts.size == 0:
            return np.zeros(counts.shape[0])
        return np.array([self.score(row)[-1] if row.size else 0.0 for row in counts])


# --------------------------------------------------------------------------- #
# count regression
# --------------------------------------------------------------------------- #
class CountGLM:
    """Log-link count regression with a ridge penalty, fitted by IRLS.

    ``family="poisson"`` maximises the Poisson log-likelihood. ``family="negbin"``
    fits the same mean structure -- the Poisson score equations are consistent
    for the mean under NB errors -- and then estimates the dispersion
    :math:`\\alpha` by profile likelihood on the fitted means. The predictive
    distribution is then :math:`\\text{NB}(\\mu, \\alpha)` with
    :math:`\\text{Var} = \\mu + \\alpha\\mu^2`, which is what makes the forecast
    intervals wide enough to be honest about outbreak clustering.

    Predictors are standardised internally using the **training** mean and
    standard deviation, which are stored; a design column that is constant in
    training is dropped rather than producing a singular system.
    """

    def __init__(
        self,
        family: str = "negbin",
        *,
        ridge: float = 1.0,
        max_iter: int = 60,
        tol: float = 1e-8,
        offset_log: bool = False,
    ) -> None:
        if family not in {"poisson", "negbin"}:
            raise ValueError(f"family must be 'poisson' or 'negbin', got {family!r}")
        self.family = family
        self.ridge = float(ridge)
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.offset_log = bool(offset_log)

        self.feature_names: list[str] = []
        self.kept_: list[str] = []
        self.coef_: np.ndarray = np.zeros(0)
        self.intercept_: float = 0.0
        self.alpha_: float = 0.05
        self.mean_: np.ndarray = np.zeros(0)
        self.scale_: np.ndarray = np.ones(0)
        self.n_obs_: int = 0
        self.log_likelihood_: float = float("nan")
        self.converged_: bool = False

    # -- internals ------------------------------------------------------- #
    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        raw = frame.reindex(columns=self.kept_).to_numpy(dtype=float)
        raw = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
        return (raw - self.mean_) / self.scale_

    # -- fitting ---------------------------------------------------------- #
    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        *,
        exposure: np.ndarray | None = None,
    ) -> CountGLM:
        frame = X.copy()
        self.feature_names = list(frame.columns)
        target = np.clip(np.asarray(y, dtype=float), 0.0, None)

        raw = np.nan_to_num(frame.to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
        sd = raw.std(axis=0)
        keep_mask = sd > 1e-9
        self.kept_ = [name for name, keep in zip(self.feature_names, keep_mask, strict=True) if keep]
        if not self.kept_:
            # Intercept-only model: still a valid (if uninformative) baseline.
            self.mean_ = np.zeros(0)
            self.scale_ = np.ones(0)
            self.coef_ = np.zeros(0)
            self.intercept_ = float(np.log(max(target.mean(), EPS)))
            self.alpha_ = fit_nb_dispersion(target, np.full_like(target, max(target.mean(), EPS)))
            self.n_obs_ = int(target.size)
            LOGGER.warning("CountGLM fitted with no usable predictors (intercept only).")
            return self

        self.mean_ = raw[:, keep_mask].mean(axis=0)
        self.scale_ = np.where(sd[keep_mask] > 1e-9, sd[keep_mask], 1.0)
        design = np.column_stack(
            [np.ones(len(frame)), (raw[:, keep_mask] - self.mean_) / self.scale_]
        )

        log_offset = (
            np.log(np.clip(np.asarray(exposure, dtype=float), EPS, None))
            if (self.offset_log and exposure is not None)
            else np.zeros(len(frame))
        )

        # Ridge on slopes only; the intercept carries the base rate.
        penalty = np.eye(design.shape[1]) * self.ridge
        penalty[0, 0] = 0.0

        beta = np.zeros(design.shape[1])
        beta[0] = np.log(max(target.mean(), EPS))
        for iteration in range(self.max_iter):
            eta = np.clip(design @ beta + log_offset, -30.0, 30.0)
            mu = np.clip(np.exp(eta), EPS, 1e8)
            # IRLS working response and weights for a log-link count model
            z = eta - log_offset + (target - mu) / mu
            w = mu
            wx = design * w[:, None]
            lhs = design.T @ wx + penalty
            rhs = wx.T @ z
            try:
                new_beta = np.linalg.solve(lhs, rhs)
            except np.linalg.LinAlgError:
                new_beta = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
            shift = float(np.max(np.abs(new_beta - beta)))
            beta = new_beta
            if shift < self.tol:
                self.converged_ = True
                break
        else:
            iteration = self.max_iter

        self.intercept_ = float(beta[0])
        self.coef_ = beta[1:]
        self.n_obs_ = int(target.size)

        mu = np.clip(np.exp(np.clip(design @ beta + log_offset, -30.0, 30.0)), EPS, 1e8)
        self.alpha_ = (
            fit_nb_dispersion(target, mu) if self.family == "negbin" else 1e-4
        )
        self.log_likelihood_ = float(
            np.sum(target * np.log(mu) - mu - np.log(np.maximum(1.0, target)) * 0.0)
        )
        LOGGER.debug(
            "CountGLM(%s): n=%s, %s predictors, alpha=%.3f, converged after %s iterations",
            self.family, self.n_obs_, len(self.kept_), self.alpha_, iteration + 1,
        )
        return self

    # -- prediction -------------------------------------------------------- #
    def predict(self, X: pd.DataFrame, *, exposure: np.ndarray | None = None) -> np.ndarray:
        """Conditional mean :math:`\\mu`."""
        if not self.kept_:
            return np.full(len(X), float(np.exp(self.intercept_)))
        eta = self.intercept_ + self._matrix(X) @ self.coef_
        if self.offset_log and exposure is not None:
            eta = eta + np.log(np.clip(np.asarray(exposure, dtype=float), EPS, None))
        return np.clip(np.exp(np.clip(eta, -30.0, 30.0)), 0.0, 1e8)

    def sample(
        self, X: pd.DataFrame, n_draws: int, *, rng: np.random.Generator | None = None
    ) -> np.ndarray:
        """``(n_rows, n_draws)`` draws from the predictive distribution."""
        mu = self.predict(X)
        rng = rng or np.random.default_rng(0)
        return nb_rvs(mu[:, None], self.alpha_, size=(mu.size, n_draws), rng=rng).astype(float)

    def quantiles(self, X: pd.DataFrame, quantiles: Sequence[float]) -> np.ndarray:
        """``(n_rows, n_quantiles)`` predictive quantiles."""
        mu = self.predict(X)
        q = np.asarray(quantiles, dtype=float)
        return np.column_stack([nb_quantile(level, mu, self.alpha_) for level in q])

    def coefficients(self) -> pd.DataFrame:
        """Standardised coefficients, largest absolute effect first."""
        return (
            pd.DataFrame({"feature": self.kept_, "coefficient": self.coef_})
            .assign(abs_coefficient=lambda d: d["coefficient"].abs())
            .sort_values("abs_coefficient", ascending=False)
            .drop(columns="abs_coefficient")
            .reset_index(drop=True)
        )

    def describe(self) -> dict[str, object]:
        return {
            "family": self.family,
            "n_obs": self.n_obs_,
            "n_predictors": len(self.kept_),
            "dispersion_alpha": round(float(self.alpha_), 4),
            "ridge": self.ridge,
            "converged": self.converged_,
        }


# --------------------------------------------------------------------------- #
# early-warning baselines
# --------------------------------------------------------------------------- #
@dataclass
class HeuristicBaseline:
    """A single-signal ranking rule, scored exactly like the fusion model.

    ``features`` are combined as a sign-weighted sum of robust z-scores across
    the rows being scored. No fitting happens, which is the point: these are
    the rules available without a modelling exercise.
    """

    name: str
    description: str
    features: tuple[str, ...]
    signs: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.signs:
            self.signs = tuple(1.0 for _ in self.features)
        if len(self.signs) != len(self.features):
            raise ValueError(f"{self.name}: signs and features must align.")

    def raw_score(self, frame: pd.DataFrame) -> np.ndarray:
        total = np.zeros(len(frame), dtype=float)
        used = 0
        for feature, sign in zip(self.features, self.signs, strict=True):
            if feature not in frame.columns:
                continue
            values = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=float)
            total += sign * np.nan_to_num(robust_z(values), nan=0.0)
            used += 1
        if used == 0:
            LOGGER.warning("Baseline %s found none of its features.", self.name)
            return total
        return total / used


#: The rules a surveillance team could apply without any of this machinery.
EARLY_WARNING_BASELINES: dict[str, HeuristicBaseline] = {
    "ewma_control_chart": HeuristicBaseline(
        name="ewma_control_chart",
        description="EWMA z-score of the country's own officially visible series.",
        features=("obs_ewma_z",),
    ),
    "recent_activity": HeuristicBaseline(
        name="recent_activity",
        description="Persistence: rank by officially reported burden in the last 4 weeks.",
        features=("obs_last_4w",),
    ),
    "seasonal_excess": HeuristicBaseline(
        name="seasonal_excess",
        description="Excess of the recent level over the week-of-year climatology.",
        features=("hist_excess_over_baseline",),
    ),
    "intelligence_only": HeuristicBaseline(
        name="intelligence_only",
        description="Redundancy-discounted media/aggregator anomaly alone.",
        features=("intel_fused_anomaly",),
    ),
    "neighbour_activity": HeuristicBaseline(
        name="neighbour_activity",
        description="Distance-weighted officially reported activity in neighbouring countries.",
        features=("spa_neighbour_activity_4w",),
    ),
    "environmental_only": HeuristicBaseline(
        name="environmental_only",
        description="Disease-specific environmental suitability alone.",
        features=("env_suitability_4w",),
    ),
}

#: Features derivable from the official record alone -- the "surveillance as
#: usual" information set. Used by :class:`OfficialRecordOnlyBaseline`.
OFFICIAL_ONLY_FEATURES: tuple[str, ...] = tuple(TEMPORAL_FEATURES) + tuple(BASELINE_FEATURES)


class OfficialRecordOnlyBaseline:
    """Logistic regression on official-record features only.

    This is the competitor that matters. It is a genuinely fitted model with
    access to the full vintage-correct WAHIS history -- trend, seasonality,
    persistence, time since last notification -- and to nothing else. The
    difference between this and the full model is the measured value of adding
    environmental, exposure, spatial and intelligence evidence.
    """

    name = "official_record_only_logistic"

    def __init__(self, *, features: Sequence[str] | None = None, C: float = 1.0) -> None:
        self.features = list(features or OFFICIAL_ONLY_FEATURES)
        self._pipeline = Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(C=float(C), max_iter=2000, solver="lbfgs")),
            ]
        )
        self.fitted_ = False
        self.n_obs_ = 0

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> OfficialRecordOnlyBaseline:
        frame = X.reindex(columns=self.features).astype(float)
        frame = frame.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        target = np.asarray(y, dtype=int)
        self.n_obs_ = int(len(frame))
        if target.size and 0 < target.sum() < target.size:
            self._pipeline.fit(frame, target)
            self.fitted_ = True
        else:
            LOGGER.warning("OfficialRecordOnlyBaseline: degenerate target, not fitted.")
        return self

    def raw_score(self, X: pd.DataFrame) -> np.ndarray:
        frame = X.reindex(columns=self.features).astype(float)
        frame = frame.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if not self.fitted_:
            return np.zeros(len(frame))
        return self._pipeline.decision_function(frame)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        frame = X.reindex(columns=self.features).astype(float)
        frame = frame.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if not self.fitted_:
            return np.full(len(frame), 0.5)
        return self._pipeline.predict_proba(frame)[:, 1]

    def coefficients(self) -> pd.DataFrame:
        if not self.fitted_:
            return pd.DataFrame(columns=["feature", "coefficient"])
        model: LogisticRegression = self._pipeline.named_steps["model"]
        return (
            pd.DataFrame({"feature": self.features, "coefficient": model.coef_[0]})
            .assign(abs_coefficient=lambda d: d["coefficient"].abs())
            .sort_values("abs_coefficient", ascending=False)
            .drop(columns="abs_coefficient")
            .reset_index(drop=True)
        )


# --------------------------------------------------------------------------- #
# panel helpers
# --------------------------------------------------------------------------- #
def control_chart_panel(
    history: OfficialHistory,
    as_of: DateLike,
    *,
    ewma: EWMAAnomalyDetector | None = None,
    cusum: CUSUMDetector | None = None,
) -> pd.DataFrame:
    """EWMA and CUSUM statistics for every entity at one as-of date."""
    ewma = ewma or EWMAAnomalyDetector()
    cusum = cusum or CUSUMDetector()
    as_of_date = ensure_date(as_of)
    w_now = history.week_position(iso_week_start(as_of_date))
    counts = history.counts_as_of(as_of_date)[:, : w_now + 1]
    return pd.DataFrame(
        {
            "entity_key": history.entities,
            "as_of": pd.Timestamp(as_of_date),
            "ewma_z": ewma.score_panel(counts),
            "ewma_alarm": (ewma.score_panel(counts) >= ewma.threshold).astype(int),
            "cusum": cusum.score_panel(counts),
            "cusum_alarm": (cusum.score_panel(counts) > cusum.h).astype(int),
        }
    )
