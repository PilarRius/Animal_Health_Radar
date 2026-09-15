"""Statistical primitives shared by the models and the evaluation suite.

Everything here is implemented directly on top of :mod:`numpy` / :mod:`scipy`
so that the project has no hard dependency on ``statsmodels``. The negative
binomial parameterisation used throughout is the *mean-dispersion* one::

    Y ~ NB(mu, alpha)      Var[Y] = mu + alpha * mu^2

with ``alpha -> 0`` recovering the Poisson. In ``scipy.stats.nbinom`` terms
``n = 1/alpha`` and ``p = n / (n + mu)``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy import optimize, special, stats

__all__ = [
    "EPS",
    "nb_params",
    "nb_pmf",
    "nb_cdf",
    "nb_quantile",
    "nb_rvs",
    "fit_nb_dispersion",
    "safe_log",
    "logit",
    "expit",
    "ewma",
    "ewma_z_score",
    "robust_z",
    "crps_empirical",
    "crps_count_cdf",
    "pit_values",
    "interval_coverage",
    "weighted_quantile",
    "mixture_quantiles",
    "normalise_01",
    "brier_score",
    "expected_calibration_error",
]

EPS: float = 1e-9


# --------------------------------------------------------------------------- #
# negative binomial helpers
# --------------------------------------------------------------------------- #
def nb_params(mu: np.ndarray | float, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Convert (mean, dispersion) to scipy's ``(n, p)`` parameterisation."""
    mu_arr = np.clip(np.asarray(mu, dtype=float), EPS, None)
    alpha = float(max(alpha, EPS))
    n = np.full_like(mu_arr, 1.0 / alpha)
    p = n / (n + mu_arr)
    return n, p


def nb_pmf(k: np.ndarray | int, mu: np.ndarray | float, alpha: float) -> np.ndarray:
    n, p = nb_params(mu, alpha)
    return stats.nbinom.pmf(k, n, p)


def nb_cdf(k: np.ndarray | int, mu: np.ndarray | float, alpha: float) -> np.ndarray:
    n, p = nb_params(mu, alpha)
    return stats.nbinom.cdf(k, n, p)


def nb_quantile(q: np.ndarray | float, mu: np.ndarray | float, alpha: float) -> np.ndarray:
    n, p = nb_params(mu, alpha)
    return stats.nbinom.ppf(q, n, p)


def nb_rvs(
    mu: np.ndarray | float, alpha: float, size: int | tuple[int, ...] | None = None,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Draw negative binomial variates via the Gamma-Poisson mixture."""
    rng = rng or np.random.default_rng()
    mu_arr = np.clip(np.asarray(mu, dtype=float), EPS, None)
    alpha = float(max(alpha, EPS))
    shape = 1.0 / alpha
    lam = rng.gamma(shape=shape, scale=mu_arr / shape, size=size)
    return rng.poisson(lam)


def fit_nb_dispersion(y: np.ndarray, mu: np.ndarray, *, max_alpha: float = 50.0) -> float:
    """Profile-likelihood estimate of the NB dispersion given fitted means.

    Solves ``argmax_alpha sum log NB(y_i | mu_i, alpha)`` on a bounded interval.
    Returns a small positive floor when the data are Poisson-like or degenerate.
    """
    y = np.asarray(y, dtype=float)
    mu = np.clip(np.asarray(mu, dtype=float), EPS, None)
    if y.size < 3 or np.allclose(y, y[0]):
        return 0.05

    def neg_ll(log_alpha: float) -> float:
        alpha = float(np.exp(log_alpha))
        r = 1.0 / alpha
        # log NB pmf in mean-dispersion form
        ll = (
            special.gammaln(y + r)
            - special.gammaln(r)
            - special.gammaln(y + 1.0)
            + r * np.log(r / (r + mu))
            + y * np.log(mu / (r + mu))
        )
        value = -float(np.sum(ll))
        return value if np.isfinite(value) else 1e12

    result = optimize.minimize_scalar(
        neg_ll, bounds=(np.log(1e-4), np.log(max_alpha)), method="bounded"
    )
    alpha = float(np.exp(result.x)) if result.success else 0.2
    return float(np.clip(alpha, 1e-4, max_alpha))


# --------------------------------------------------------------------------- #
# transforms
# --------------------------------------------------------------------------- #
def safe_log(x: np.ndarray | float, offset: float = 1.0) -> np.ndarray:
    return np.log(np.clip(np.asarray(x, dtype=float) + offset, EPS, None))


def logit(p: np.ndarray | float, clip: float = 1e-6) -> np.ndarray:
    p_arr = np.clip(np.asarray(p, dtype=float), clip, 1.0 - clip)
    return np.log(p_arr / (1.0 - p_arr))


def expit(x: np.ndarray | float) -> np.ndarray:
    return special.expit(np.asarray(x, dtype=float))


def normalise_01(x: np.ndarray, *, lo: float | None = None, hi: float | None = None) -> np.ndarray:
    """Min-max scale to [0, 1], robust to constant input."""
    arr = np.asarray(x, dtype=float)
    low = np.nanmin(arr) if lo is None else lo
    high = np.nanmax(arr) if hi is None else hi
    if not np.isfinite(low) or not np.isfinite(high) or high - low < EPS:
        return np.zeros_like(arr)
    return np.clip((arr - low) / (high - low), 0.0, 1.0)


# --------------------------------------------------------------------------- #
# anomaly detection
# --------------------------------------------------------------------------- #
def ewma(x: Sequence[float] | np.ndarray, alpha: float = 0.3) -> np.ndarray:
    """Exponentially weighted moving average (causal: uses only the past)."""
    arr = np.asarray(x, dtype=float)
    out = np.empty_like(arr)
    if arr.size == 0:
        return out
    level = arr[0] if np.isfinite(arr[0]) else 0.0
    for i, value in enumerate(arr):
        if np.isfinite(value):
            level = alpha * value + (1.0 - alpha) * level
        out[i] = level
    return out


def ewma_z_score(
    x: Sequence[float] | np.ndarray, alpha: float = 0.3, min_sd: float = 0.5
) -> np.ndarray:
    """Causal EWMA control-chart statistic.

    For each time ``t`` the observation is compared with the EWMA level and
    EWMA variance computed from ``t-1`` and earlier only. This makes the
    statistic usable at the edge of a real-time data stream without leakage.
    """
    arr = np.asarray(x, dtype=float)
    n = arr.size
    z = np.zeros(n, dtype=float)
    if n == 0:
        return z
    level = float(arr[0]) if np.isfinite(arr[0]) else 0.0
    var = max(float(np.nanvar(arr[: min(8, n)])), min_sd**2)
    for t in range(n):
        value = float(arr[t]) if np.isfinite(arr[t]) else level
        sd = max(np.sqrt(max(var, 0.0)), min_sd)
        z[t] = (value - level) / sd
        # update AFTER scoring => strictly causal
        residual = value - level
        level = alpha * value + (1.0 - alpha) * level
        var = alpha * residual**2 + (1.0 - alpha) * var
    return z


def robust_z(x: np.ndarray, *, min_scale: float = 0.5) -> np.ndarray:
    """Median/MAD standardisation, resistant to the outbreak spikes themselves."""
    arr = np.asarray(x, dtype=float)
    med = np.nanmedian(arr)
    mad = np.nanmedian(np.abs(arr - med)) * 1.4826
    scale = max(float(mad), min_scale)
    return (arr - med) / scale


# --------------------------------------------------------------------------- #
# probabilistic forecast scoring
# --------------------------------------------------------------------------- #
def crps_empirical(samples: np.ndarray, observation: float) -> float:
    """CRPS of an empirical predictive distribution (Hersbach decomposition).

    ``CRPS = E|X - y| - 0.5 * E|X - X'|`` estimated from Monte-Carlo draws.
    Lower is better; it is in the units of the observation.
    """
    x = np.sort(np.asarray(samples, dtype=float))
    n = x.size
    if n == 0 or not np.isfinite(observation):
        return float("nan")
    term1 = float(np.mean(np.abs(x - observation)))
    # E|X - X'| via the sorted-sample identity, O(n)
    i = np.arange(1, n + 1)
    term2 = float(2.0 * np.sum((2 * i - n - 1) * x) / (n * n))
    return term1 - 0.5 * term2


def crps_count_cdf(cdf_values: np.ndarray, support: np.ndarray, observation: float) -> float:
    """CRPS for a discrete count distribution given its CDF on a support grid.

    ``CRPS = sum_k (F(k) - 1{y <= k})^2`` over the integer support.
    """
    f = np.asarray(cdf_values, dtype=float)
    k = np.asarray(support, dtype=float)
    if f.size == 0 or not np.isfinite(observation):
        return float("nan")
    indicator = (k >= observation).astype(float)
    return float(np.sum((f - indicator) ** 2))


def pit_values(cdf_at_y: np.ndarray, cdf_at_y_minus_1: np.ndarray | None = None) -> np.ndarray:
    """Probability integral transform values, randomised for count data."""
    upper = np.asarray(cdf_at_y, dtype=float)
    if cdf_at_y_minus_1 is None:
        return upper
    lower = np.asarray(cdf_at_y_minus_1, dtype=float)
    return 0.5 * (lower + upper)


def interval_coverage(
    observed: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> float:
    """Empirical coverage of a prediction interval."""
    y = np.asarray(observed, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    valid = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if valid.sum() == 0:
        return float("nan")
    inside = (y[valid] >= lo[valid]) & (y[valid] <= hi[valid])
    return float(np.mean(inside))


def weighted_quantile(
    values: np.ndarray, quantiles: Sequence[float], weights: np.ndarray | None = None
) -> np.ndarray:
    """Weighted quantiles of a sample (used for ensemble predictive intervals)."""
    v = np.asarray(values, dtype=float)
    q = np.asarray(quantiles, dtype=float)
    if weights is None:
        return np.quantile(v, q)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(v)
    v, w = v[order], w[order]
    cum = np.cumsum(w) - 0.5 * w
    cum /= np.sum(w)
    return np.interp(q, cum, v)


def mixture_quantiles(
    component_samples: Sequence[np.ndarray],
    weights: Sequence[float],
    quantiles: Sequence[float],
    rng: np.random.Generator | None = None,
    n_draws: int = 4000,
) -> np.ndarray:
    """Quantiles of a weighted mixture of predictive samples.

    Draws are taken from each component in proportion to its weight, giving a
    genuine mixture rather than an average of quantiles (which would understate
    the spread when members disagree).
    """
    rng = rng or np.random.default_rng(0)
    w = np.asarray(weights, dtype=float)
    w = w / max(w.sum(), EPS)
    pooled: list[np.ndarray] = []
    for samples, weight in zip(component_samples, w, strict=True):
        arr = np.asarray(samples, dtype=float)
        if arr.size == 0 or weight <= 0:
            continue
        take = max(int(round(weight * n_draws)), 1)
        idx = rng.integers(0, arr.size, size=take)
        pooled.append(arr[idx])
    if not pooled:
        return np.full(len(quantiles), np.nan)
    stacked = np.concatenate(pooled)
    return np.quantile(stacked, np.asarray(quantiles, dtype=float))


# --------------------------------------------------------------------------- #
# classification calibration metrics
# --------------------------------------------------------------------------- #
def brier_score(y_true: np.ndarray, p_pred: np.ndarray) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(p_pred, dtype=float)
    valid = np.isfinite(y) & np.isfinite(p)
    if valid.sum() == 0:
        return float("nan")
    return float(np.mean((p[valid] - y[valid]) ** 2))


def expected_calibration_error(
    y_true: np.ndarray, p_pred: np.ndarray, n_bins: int = 10
) -> float:
    """ECE with equal-width bins on the predicted probability."""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(p_pred, dtype=float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    if y.size == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges, right=True) - 1, 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        ece += (mask.sum() / y.size) * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return float(ece)
