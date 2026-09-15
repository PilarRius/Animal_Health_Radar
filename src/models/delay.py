"""Reporting-delay model: the observation process, estimated rather than assumed.

What is modelled
----------------
The delay :math:`D` between when an outbreak *happened* (reference date, in
practice the onset week) and when it *became knowable* (the date the official
record was published). This is the quantity that determines how much of the
present is currently invisible.

Right-truncation is the whole problem
-------------------------------------
At any analysis date :math:`T`, an outbreak with reference date :math:`t` is in
the data only if its delay satisfies :math:`D \\le T - t`. Fitting a delay
distribution to the observed delays without accounting for that selection
produces a systematically **too short** delay -- and therefore a nowcast that
systematically **understates** hidden burden, which is the exact failure mode
this system exists to avoid.

The likelihood used here is the truncated one:

.. math::

    L = \\prod_i \\frac{f(d_i \\mid \\theta)}{F(T - t_i \\mid \\theta)}

Two families are fitted (discretised log-normal and negative binomial) and the
better AIC wins, per group.

Partial pooling
---------------
Delay behaviour varies by disease and by veterinary service capacity, but many
strata are thin. Groups are fitted at ``(disease, surveillance capacity tier)``
and shrunk towards the disease-level fit, which is itself shrunk towards the
global fit, with weight :math:`n / (n + \\kappa)`. Thin strata therefore borrow
strength instead of producing noise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from src.schemas.outputs import ReportingEstimate
from src.utils.config import AppConfig, get_config, load_countries
from src.utils.dates import DateLike, ensure_date
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["DelayFit", "ReportingDelayModel"]

_MAX_DELAY_FLOOR = 7
_SHRINKAGE_KAPPA = 40.0


@dataclass
class DelayFit:
    """Fitted delay distribution for one group."""

    group: str
    family: str                     # "lognormal" | "negbin"
    params: tuple[float, ...]
    n_observations: int
    log_likelihood: float
    aic: float
    truncated: bool = True
    pooled_with_parent: bool = False
    shrinkage_weight: float = 1.0
    parent: str | None = None
    diagnostics: dict[str, float] = field(default_factory=dict)

    # -- distribution interface ------------------------------------------ #
    def cdf(self, days: np.ndarray | float) -> np.ndarray:
        d = np.clip(np.asarray(days, dtype=float), 0.0, None)
        if self.family == "lognormal":
            meanlog, sdlog = self.params
            # Discretised: P(D <= d) for integer-day support
            return stats.lognorm.cdf(d + 0.5, s=sdlog, scale=np.exp(meanlog))
        mu, alpha = self.params
        n = 1.0 / max(alpha, 1e-6)
        p = n / (n + mu)
        return stats.nbinom.cdf(np.floor(d), n, p)

    def pmf(self, days: np.ndarray | float) -> np.ndarray:
        d = np.clip(np.asarray(days, dtype=float), 0.0, None)
        if self.family == "lognormal":
            meanlog, sdlog = self.params
            upper = stats.lognorm.cdf(d + 0.5, s=sdlog, scale=np.exp(meanlog))
            lower = stats.lognorm.cdf(np.clip(d - 0.5, 0.0, None), s=sdlog, scale=np.exp(meanlog))
            return np.clip(upper - lower, 0.0, 1.0)
        mu, alpha = self.params
        n = 1.0 / max(alpha, 1e-6)
        p = n / (n + mu)
        return stats.nbinom.pmf(np.floor(d), n, p)

    @property
    def mean(self) -> float:
        if self.family == "lognormal":
            meanlog, sdlog = self.params
            return float(np.exp(meanlog + 0.5 * sdlog**2))
        return float(self.params[0])

    @property
    def median(self) -> float:
        if self.family == "lognormal":
            return float(np.exp(self.params[0]))
        return float(self.quantile(0.5))

    def quantile(self, q: float) -> float:
        if self.family == "lognormal":
            meanlog, sdlog = self.params
            return float(stats.lognorm.ppf(q, s=sdlog, scale=np.exp(meanlog)))
        mu, alpha = self.params
        n = 1.0 / max(alpha, 1e-6)
        p = n / (n + mu)
        return float(stats.nbinom.ppf(q, n, p))

    def to_dict(self) -> dict[str, object]:
        return {
            "group": self.group,
            "family": self.family,
            "params": list(self.params),
            "n_observations": self.n_observations,
            "log_likelihood": round(self.log_likelihood, 3),
            "aic": round(self.aic, 3),
            "mean_days": round(self.mean, 2),
            "median_days": round(self.median, 2),
            "p90_days": round(self.quantile(0.9), 2),
            "truncated_likelihood": self.truncated,
            "pooled_with_parent": self.pooled_with_parent,
            "shrinkage_weight": round(self.shrinkage_weight, 3),
            "parent": self.parent,
        }


class ReportingDelayModel:
    """Hierarchical, right-truncation-corrected reporting delay model."""

    GLOBAL_KEY = "__global__"

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.max_delay_days = int(self.config.get("nowcast.max_delay_days", 120))
        self.min_reporting_probability = float(
            self.config.get("nowcast.min_reporting_probability", 0.08)
        )
        self.fits: dict[str, DelayFit] = {}
        self.as_of: date | None = None
        self._capacity = {
            iso: spec.surveillance_capacity for iso, spec in load_countries().items()
        }

    # ------------------------------------------------------------------ #
    # fitting
    # ------------------------------------------------------------------ #
    def fit(
        self,
        events: pd.DataFrame,
        as_of: DateLike,
        *,
        reference_col: str = "reference_date",
        available_col: str = "available_from",
    ) -> ReportingDelayModel:
        """Fit the hierarchy using only records knowable at *as_of*."""
        self.as_of = ensure_date(as_of)
        cutoff = pd.Timestamp(self.as_of)

        frame = events.copy()
        frame[reference_col] = pd.to_datetime(frame[reference_col], errors="coerce")
        frame[available_col] = pd.to_datetime(frame[available_col], errors="coerce")
        frame = frame.loc[
            frame[reference_col].notna()
            & frame[available_col].notna()
            & (frame[available_col] <= cutoff)
        ].copy()

        frame["delay_days"] = (frame[available_col] - frame[reference_col]).dt.days
        frame["truncation_days"] = (cutoff - frame[reference_col]).dt.days
        frame = frame.loc[
            (frame["delay_days"] >= 0)
            & (frame["delay_days"] <= self.max_delay_days)
            & (frame["truncation_days"] >= 0)
        ]
        if frame.empty:
            LOGGER.warning("No usable delays at as_of=%s; using the configured prior.", self.as_of)
            self.fits = {self.GLOBAL_KEY: self._prior_fit(self.GLOBAL_KEY)}
            return self

        if "surveillance_capacity" not in frame.columns:
            frame["surveillance_capacity"] = frame["country_iso3"].map(self._capacity).fillna("medium")

        # --- level 0: global -------------------------------------------- #
        global_fit = self._fit_group(frame, self.GLOBAL_KEY)
        self.fits = {self.GLOBAL_KEY: global_fit}

        # --- level 1: disease -------------------------------------------- #
        for disease, block in frame.groupby("disease", sort=True):
            fit = self._fit_group(block, str(disease), parent=global_fit)
            self.fits[str(disease)] = fit

        # --- level 2: disease x capacity tier ----------------------------- #
        for (disease, tier), block in frame.groupby(
            ["disease", "surveillance_capacity"], sort=True
        ):
            key = f"{disease}|{tier}"
            parent = self.fits.get(str(disease), global_fit)
            self.fits[key] = self._fit_group(block, key, parent=parent)

        LOGGER.info(
            "Delay model fitted at %s on %s truncated observations "
            "(global: %s, median %.1f d, mean %.1f d)",
            self.as_of, len(frame), global_fit.family, global_fit.median, global_fit.mean,
        )
        return self

    def _fit_group(
        self, frame: pd.DataFrame, key: str, parent: DelayFit | None = None
    ) -> DelayFit:
        delays = frame["delay_days"].to_numpy(dtype=float)
        truncation = frame["truncation_days"].to_numpy(dtype=float)
        n = int(delays.size)
        if n < 5:
            return self._inherit(parent or self._prior_fit(key), key, n)

        candidates = [
            self._fit_lognormal(delays, truncation),
            self._fit_negbin(delays, truncation),
        ]
        candidates = [c for c in candidates if c is not None]
        if not candidates:
            return self._inherit(parent or self._prior_fit(key), key, n)

        family, params, log_likelihood = min(
            candidates, key=lambda c: 2 * len(c[1]) - 2 * c[2]
        )
        aic = 2 * len(params) - 2 * log_likelihood
        fit = DelayFit(
            group=key,
            family=family,
            params=params,
            n_observations=n,
            log_likelihood=log_likelihood,
            aic=aic,
            truncated=True,
            parent=parent.group if parent else None,
            diagnostics={
                "empirical_median_uncorrected": float(np.median(delays)),
                "share_fully_observed": float(np.mean(truncation >= self.max_delay_days)),
            },
        )
        if parent is not None:
            fit = self._shrink(fit, parent)
        return fit

    # -- likelihoods ------------------------------------------------------ #
    def _fit_lognormal(
        self, delays: np.ndarray, truncation: np.ndarray
    ) -> tuple[str, tuple[float, ...], float] | None:
        shifted = np.clip(delays, 0.5, None)
        upper = np.clip(truncation, 1.0, None) + 0.5

        def neg_ll(theta: np.ndarray) -> float:
            meanlog, log_sd = float(theta[0]), float(theta[1])
            sdlog = float(np.exp(log_sd))
            if not np.isfinite(meanlog) or sdlog <= 1e-3 or sdlog > 5.0:
                return 1e12
            z = (np.log(shifted) - meanlog) / sdlog
            log_pdf = -np.log(shifted * sdlog * np.sqrt(2 * np.pi)) - 0.5 * z**2
            # Right-truncation: condition on D <= (T - t)
            log_denominator = np.log(
                np.clip(stats.norm.cdf((np.log(upper) - meanlog) / sdlog), 1e-12, 1.0)
            )
            value = -float(np.sum(log_pdf - log_denominator))
            return value if np.isfinite(value) else 1e12

        start = np.array([float(np.log(np.median(shifted))), float(np.log(0.7))])
        result = optimize.minimize(neg_ll, start, method="Nelder-Mead",
                                   options={"maxiter": 600, "xatol": 1e-4, "fatol": 1e-4})
        if not np.isfinite(result.fun) or result.fun >= 1e11:
            return None
        meanlog = float(result.x[0])
        sdlog = float(np.clip(np.exp(result.x[1]), 0.05, 3.0))
        return "lognormal", (meanlog, sdlog), -float(result.fun)

    def _fit_negbin(
        self, delays: np.ndarray, truncation: np.ndarray
    ) -> tuple[str, tuple[float, ...], float] | None:
        counts = np.floor(np.clip(delays, 0.0, None))
        upper = np.floor(np.clip(truncation, 0.0, None))

        def neg_ll(theta: np.ndarray) -> float:
            log_mu, log_alpha = float(theta[0]), float(theta[1])
            mu = float(np.exp(log_mu))
            alpha = float(np.exp(log_alpha))
            if mu <= 0 or mu > 500 or alpha <= 1e-5 or alpha > 20:
                return 1e12
            r = 1.0 / alpha
            p = r / (r + mu)
            log_pmf = (
                special.gammaln(counts + r) - special.gammaln(r) - special.gammaln(counts + 1.0)
                + r * np.log(p) + counts * np.log1p(-p)
            )
            log_denominator = np.log(np.clip(stats.nbinom.cdf(upper, r, p), 1e-12, 1.0))
            value = -float(np.sum(log_pmf - log_denominator))
            return value if np.isfinite(value) else 1e12

        start = np.array([float(np.log(max(np.mean(counts), 1.0))), float(np.log(0.5))])
        result = optimize.minimize(neg_ll, start, method="Nelder-Mead",
                                   options={"maxiter": 600, "xatol": 1e-4, "fatol": 1e-4})
        if not np.isfinite(result.fun) or result.fun >= 1e11:
            return None
        mu = float(np.exp(result.x[0]))
        alpha = float(np.clip(np.exp(result.x[1]), 1e-4, 20.0))
        return "negbin", (mu, alpha), -float(result.fun)

    # -- pooling ---------------------------------------------------------- #
    def _shrink(self, fit: DelayFit, parent: DelayFit) -> DelayFit:
        """Shrink a group fit towards its parent with weight n / (n + kappa)."""
        weight = fit.n_observations / (fit.n_observations + _SHRINKAGE_KAPPA)
        if fit.family != parent.family or weight > 0.95:
            fit.shrinkage_weight = float(weight)
            fit.pooled_with_parent = weight <= 0.95
            return fit
        blended = tuple(
            weight * own + (1.0 - weight) * other
            for own, other in zip(fit.params, parent.params, strict=True)
        )
        fit.params = blended
        fit.shrinkage_weight = float(weight)
        fit.pooled_with_parent = True
        return fit

    def _inherit(self, parent: DelayFit, key: str, n: int) -> DelayFit:
        return DelayFit(
            group=key,
            family=parent.family,
            params=parent.params,
            n_observations=n,
            log_likelihood=float("nan"),
            aic=float("nan"),
            truncated=parent.truncated,
            pooled_with_parent=True,
            shrinkage_weight=0.0,
            parent=parent.group,
        )

    def _prior_fit(self, key: str) -> DelayFit:
        """Fallback to the configured generative prior when data are absent."""
        return DelayFit(
            group=key,
            family="lognormal",
            params=(2.7, 0.7),
            n_observations=0,
            log_likelihood=float("nan"),
            aic=float("nan"),
            truncated=False,
            pooled_with_parent=True,
            shrinkage_weight=0.0,
        )

    # ------------------------------------------------------------------ #
    # prediction
    # ------------------------------------------------------------------ #
    def _resolve(self, disease: str, country_iso3: str | None = None) -> DelayFit:
        if country_iso3:
            tier = self._capacity.get(country_iso3.upper(), "medium")
            candidate = self.fits.get(f"{disease}|{tier}")
            if candidate is not None:
                return candidate
        candidate = self.fits.get(disease)
        if candidate is not None:
            return candidate
        return self.fits.get(self.GLOBAL_KEY) or self._prior_fit(self.GLOBAL_KEY)

    def resolve_fit(self, disease: str, country_iso3: str | None = None) -> DelayFit:
        """The fit that governs this entity: ``disease|tier``, then disease, then global."""
        return self._resolve(disease, country_iso3)

    def expected_delay(self, disease: str, country_iso3: str | None = None) -> float:
        return float(self._resolve(disease, country_iso3).mean)

    def median_delay(self, disease: str, country_iso3: str | None = None) -> float:
        return float(self._resolve(disease, country_iso3).median)

    def p_reported_by(
        self, days: float | np.ndarray, disease: str, country_iso3: str | None = None
    ) -> np.ndarray:
        """P(an event is publicly visible within *days* of its reference date)."""
        return np.clip(self._resolve(disease, country_iso3).cdf(days), 0.0, 1.0)

    def reporting_probability(
        self,
        reference_week: DateLike,
        as_of: DateLike,
        disease: str,
        country_iso3: str | None = None,
        *,
        week_midpoint_offset: float = 3.0,
    ) -> float:
        """Share of a reference week's events expected to be visible by *as_of*.

        The week's events are spread over seven days, so the elapsed time is
        measured from the week's midpoint rather than its Monday.
        """
        reference = ensure_date(reference_week)
        cutoff = ensure_date(as_of)
        if reference is None or cutoff is None:
            return 1.0
        elapsed = (cutoff - reference).days - week_midpoint_offset
        if elapsed < 0:
            return float(self.min_reporting_probability)
        probability = float(self.p_reported_by(elapsed, disease, country_iso3))
        return float(np.clip(probability, self.min_reporting_probability, 1.0))

    def estimate(
        self,
        entity_key: str,
        as_of: DateLike,
        reference_week: DateLike,
    ) -> ReportingEstimate:
        """Full :class:`ReportingEstimate` for one entity."""
        country, disease = entity_key.split("|")
        fit = self._resolve(disease, country)
        return ReportingEstimate(
            entity_key=entity_key,
            as_of=ensure_date(as_of),  # type: ignore[arg-type]
            distribution=fit.family,
            expected_reporting_delay=float(max(fit.mean, 0.0)),
            median_reporting_delay=float(max(fit.median, 0.0)),
            delay_p90=float(max(fit.quantile(0.9), 0.0)),
            reporting_probability=self.reporting_probability(
                reference_week, as_of, disease, country
            ),
            p_reported_by={
                str(k): float(self.p_reported_by(k, disease, country)) for k in (7, 14, 28, 60)
            },
            n_observations=fit.n_observations,
            pooled_with_global=fit.pooled_with_parent,
            shrinkage_weight=fit.shrinkage_weight,
        )

    # ------------------------------------------------------------------ #
    # reporting
    # ------------------------------------------------------------------ #
    def summary(self) -> pd.DataFrame:
        return pd.DataFrame([fit.to_dict() for fit in self.fits.values()]).sort_values("group")

    def entity_features(self, entities: Sequence[str], as_of: DateLike, reference_week: DateLike) -> pd.DataFrame:
        """Delay-derived features for the design matrix (reporting behaviour family)."""
        rows: list[dict[str, object]] = []
        for key in entities:
            country, disease = key.split("|")
            fit = self._resolve(disease, country)
            rows.append(
                {
                    "entity_key": key,
                    "rep_expected_delay_days": float(fit.mean),
                    "rep_median_delay_days": float(fit.median),
                    "rep_delay_p90_days": float(fit.quantile(0.9)),
                    "rep_reporting_probability": self.reporting_probability(
                        reference_week, as_of, disease, country
                    ),
                    "rep_p_reported_14d": float(self.p_reported_by(14, disease, country)),
                }
            )
        return pd.DataFrame(rows)
