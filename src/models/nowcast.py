r"""Nowcast: separating the disease process from the observation process.

The problem
-----------
The officially visible count for a recent week is not a measurement of disease
activity. It is a measurement of *disease activity that has already completed
the notification chain*. For the current week that chain is typically 10-30%
complete, so reading the visible series as if it were the epidemic curve makes
every outbreak look like it is ending.

The estimator
-------------
Two distinct unknowns are recovered, and they are kept separate on purpose.

**1. What will eventually be reported for this week.**
Let :math:`O_w` be the burden for reference week *w* that is visible at
``as_of``, and :math:`p_w` the probability -- from the fitted, right-truncation
corrected :class:`~src.models.delay.ReportingDelayModel` -- that an event with
reference week *w* is already visible. With a Gamma :math:`(a_0, b_0)` prior on
the weekly rate and Poisson reporting, the not-yet-reported remainder has a
closed-form negative binomial posterior predictive:

.. math::

    U_w \mid O_w \;\sim\; \mathrm{NB}\!\left(r = a_0 + O_w,\;
        q = \frac{b_0 + p_w}{b_0 + 1}\right),
    \qquad
    \mathbb{E}[U_w] = (a_0 + O_w)\,\frac{1 - p_w}{b_0 + p_w}

so :math:`\hat{N}_w = O_w + U_w`. As :math:`a_0, b_0 \to 0` the mean collapses
to the inverse-probability estimate :math:`O_w / p_w`; the weakly informative
prior exists only to keep the estimator finite when :math:`p_w` is small and
:math:`O_w = 0`, which is exactly the situation at the leading edge.

**2. What was never reported at all.**
Ascertainment -- the probability that a true outbreak is *ever* detected -- is
**not identifiable from official data alone**. No amount of modelling of WAHIS
recovers outbreaks that WAHIS never saw. It is therefore supplied as an
explicit Beta prior per surveillance-capacity tier in
``config/config.yaml: ascertainment``, with a disease multiplier (ASF in wild
boar is harder to see than HPAI in commercial poultry). Every nowcast object
carries ``ascertainment_mean`` and ``ascertainment_source`` so the assumption
travels with the number and is never mistaken for an estimate.

.. math::

    \text{latent}_w = \frac{\hat{N}_w}{a}, \qquad a \sim \mathrm{Beta}(\alpha_{\text{tier}}, \beta_{\text{tier}}) \cdot m_{\text{disease}}

Borrowing strength across weeks
-------------------------------
Week-by-week estimates are independent and noisy, and the noise grows as
:math:`p_w` falls. A local-level (random-walk) state-space model is therefore
run over the nowcast window on the log scale, with the per-week Monte-Carlo
variance as the observation variance, and smoothed by the Rauch-Tung-Striebel
recursions. Weeks that are nearly complete anchor the trajectory; the
poorly-observed leading edge is pulled towards it instead of swinging on one
late notification. The predictive *spread* is taken from the Monte-Carlo draws,
so smoothing sharpens the location estimate without pretending the uncertainty
went away.

Uncertainty propagated
----------------------
1. sampling of the unreported remainder (NB posterior predictive);
2. estimation error in :math:`p_w`, as a Beta perturbation whose concentration
   is the number of delay observations behind the fit;
3. the ascertainment prior.

What is *not* propagated: structural error in the delay family itself, and any
possibility that the synthetic corpus misrepresents real reporting behaviour.
Both are limitations, documented in ``docs/MODEL_CARD.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.features.temporal import OfficialHistory
from src.models.delay import ReportingDelayModel
from src.schemas.outputs import NowcastObject, ReportingEstimate
from src.utils.bands import band_for
from src.utils.config import AppConfig, get_config, load_countries, load_thresholds
from src.utils.dates import DateLike, ensure_date, iso_week_start
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["LatentStateNowcastModel", "AscertainmentPrior", "NOWCAST_PANEL_COLUMNS"]

#: Columns written to ``data/processed/nowcasts.parquet``.
NOWCAST_PANEL_COLUMNS: list[str] = [
    "entity_key", "country_iso3", "disease", "as_of", "reference_week",
    "observed_disease_burden", "reporting_probability", "expected_reporting_delay",
    "latent_disease_estimate", "nowcast_lower", "nowcast_upper", "interval_level",
    "estimated_hidden_burden", "reporting_gap", "reporting_gap_band",
    "ascertainment_mean", "ascertainment_source", "method", "confidence",
    "n_contributing_records", "is_reference_week",
    "observed_4w", "latent_4w", "hidden_4w", "reporting_gap_4w",
]


class AscertainmentPrior:
    """The explicit, auditable assumption about what is never reported.

    This class exists so that the assumption has a name, a source string and a
    single place to change. It is a *prior*, not an estimate: the official
    record contains no information with which to identify it.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        config = config or get_config()
        self.enabled = bool(config.get("ascertainment.enabled", True))
        self._priors: dict[str, tuple[float, float]] = {
            str(tier): (float(spec.get("alpha", 1.0)), float(spec.get("beta", 1.0)))
            for tier, spec in (config.get("ascertainment.priors", {}) or {}).items()
        }
        self._multiplier: dict[str, float] = {
            str(code).upper(): float(value)
            for code, value in (config.get("ascertainment.disease_multiplier", {}) or {}).items()
        }
        self._capacity = {
            iso: spec.surveillance_capacity for iso, spec in load_countries().items()
        }
        self.source = "config/config.yaml: ascertainment (PRIOR, not an estimate)"

    def tier(self, country_iso3: str) -> str:
        return self._capacity.get(str(country_iso3).upper(), "medium")

    def params(self, country_iso3: str, disease: str) -> tuple[float, float, float]:
        """``(alpha, beta, disease_multiplier)`` for one entity."""
        alpha, beta = self._priors.get(self.tier(country_iso3), (10.0, 8.0))
        return alpha, beta, self._multiplier.get(str(disease).upper(), 1.0)

    def mean(self, country_iso3: str, disease: str) -> float:
        """Prior mean detection probability. ``1.0`` when disabled."""
        if not self.enabled:
            return 1.0
        alpha, beta, multiplier = self.params(country_iso3, disease)
        return float(np.clip(alpha / max(alpha + beta, 1e-9) * multiplier, 0.05, 1.0))

    def draw(
        self, country_iso3: str, disease: str, size: int, rng: np.random.Generator
    ) -> np.ndarray:
        if not self.enabled:
            return np.ones(size)
        alpha, beta, multiplier = self.params(country_iso3, disease)
        return np.clip(rng.beta(alpha, beta, size=size) * multiplier, 0.05, 1.0)

    def describe(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "source": self.source,
            "priors_by_capacity_tier": {
                tier: {"alpha": a, "beta": b, "prior_mean": round(a / (a + b), 4)}
                for tier, (a, b) in self._priors.items()
            },
            "disease_multiplier": dict(self._multiplier),
            "identifiability_note": (
                "Detection probability is not identifiable from official notification "
                "data alone; this is a stated assumption propagated into the intervals."
            ),
        }


class LatentStateNowcastModel:
    """Latent activity and reporting-gap estimation for one as-of date."""

    method = "nb_completion_ipw_local_level_v1"

    def __init__(
        self,
        delay_model: ReportingDelayModel | None = None,
        *,
        config: AppConfig | None = None,
        prior_shape: float = 0.5,
        prior_rate: float = 0.1,
        random_seed: int | None = None,
    ) -> None:
        self.config = config or get_config()
        self.delay_model = delay_model
        self.ascertainment = AscertainmentPrior(self.config)
        self.prior_shape = float(prior_shape)   # a0 (Jeffreys-ish)
        self.prior_rate = float(prior_rate)     # b0 (weakly informative)
        self.window_weeks = int(self.config.get("nowcast.nowcast_window_weeks", 12))
        self.min_p = float(self.config.get("nowcast.min_reporting_probability", 0.08))
        self.interval_level = float(self.config.central_interval)
        self.n_draws = int(self.config.mc_draws)
        self._seed = int(random_seed if random_seed is not None else self.config.random_seed)
        self._gap_bands = (load_thresholds().get("reporting_gap", {}) or {})

    # ------------------------------------------------------------------ #
    # fitting
    # ------------------------------------------------------------------ #
    def fit(self, events: pd.DataFrame, as_of: DateLike) -> LatentStateNowcastModel:
        """Fit (or refit) the underlying delay model using only pre-*as_of* records."""
        model = ReportingDelayModel(config=self.config)
        model.fit(events, as_of=as_of)
        self.delay_model = model
        return self

    def _require_delay_model(self) -> ReportingDelayModel:
        if self.delay_model is None:
            raise RuntimeError(
                "LatentStateNowcastModel has no delay model. Call .fit(events, as_of) or "
                "pass one to the constructor."
            )
        return self.delay_model

    # ------------------------------------------------------------------ #
    # core estimator
    # ------------------------------------------------------------------ #
    def _entity_draws(
        self,
        *,
        observed: np.ndarray,
        p: np.ndarray,
        n_delay_obs: int,
        country_iso3: str,
        disease: str,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """``(n_weeks, n_draws)`` latent-burden draws for one entity.

        Combines the three uncertainty sources described in the module
        docstring. ``p`` is the per-week probability that the week is already
        visible; ``observed`` the visible burden for the same weeks.
        """
        n_weeks = observed.size
        draws = self.n_draws

        # (1) estimation error in p: Beta perturbation whose concentration is
        #     the number of truncated delay observations behind the fit.
        concentration = float(np.clip(n_delay_obs, 20.0, 5000.0))
        p_matrix = np.empty((n_weeks, draws))
        for w in range(n_weeks):
            p_w = float(np.clip(p[w], self.min_p, 1.0 - 1e-6))
            p_matrix[w] = np.clip(
                rng.beta(concentration * p_w, concentration * (1.0 - p_w), size=draws),
                self.min_p, 1.0,
            )

        # (2) not-yet-reported remainder: NB posterior predictive.
        a0, b0 = self.prior_shape, self.prior_rate
        r = np.broadcast_to(a0 + observed[:, None], p_matrix.shape)
        q = np.clip((b0 + p_matrix) / (b0 + 1.0), 1e-4, 1.0 - 1e-9)
        unreported = rng.negative_binomial(r, q).astype(float)
        eventually_reported = observed[:, None] + unreported

        # (3) ascertainment prior: what is never reported at all.
        ascertainment = self.ascertainment.draw(country_iso3, disease, draws, rng)
        latent = eventually_reported / ascertainment[None, :]

        # A latent count below what has already been reported is incoherent.
        return np.maximum(latent, observed[:, None])

    @staticmethod
    def _local_level_smoother(
        y: np.ndarray, obs_var: np.ndarray, *, min_state_var: float = 0.02
    ) -> tuple[np.ndarray, np.ndarray]:
        """Random-walk (local level) filter + RTS smoother on a log-scale series.

        The state variance is estimated empirically as the part of the
        successive-difference variance that the observation noise cannot
        explain, floored so the smoother never becomes a straight line.
        """
        n = y.size
        if n == 0:
            return y, obs_var
        if n == 1:
            return y.copy(), obs_var.copy()

        diffs = np.diff(y)
        state_var = max(
            0.5 * float(np.median(diffs**2)) - float(np.median(obs_var)), min_state_var
        )

        # forward filter
        a = np.zeros(n)          # filtered state mean
        P = np.zeros(n)          # filtered state variance
        a_pred = np.zeros(n)
        P_pred = np.zeros(n)
        a_prev, P_prev = float(y[0]), max(float(obs_var[0]), min_state_var) + state_var
        for t in range(n):
            a_pred[t] = a_prev
            P_pred[t] = P_prev + (state_var if t > 0 else 0.0)
            v = max(float(obs_var[t]), 1e-6)
            gain = P_pred[t] / (P_pred[t] + v)
            a[t] = a_pred[t] + gain * (y[t] - a_pred[t])
            P[t] = (1.0 - gain) * P_pred[t]
            a_prev, P_prev = a[t], P[t]

        # RTS backward smoother
        a_smooth = a.copy()
        P_smooth = P.copy()
        for t in range(n - 2, -1, -1):
            denom = P[t] + state_var
            j = P[t] / denom if denom > 0 else 0.0
            a_smooth[t] = a[t] + j * (a_smooth[t + 1] - (a[t]))
            P_smooth[t] = P[t] + j**2 * (P_smooth[t + 1] - denom)
        return a_smooth, np.clip(P_smooth, 0.0, None)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def nowcast(
        self,
        history: OfficialHistory,
        as_of: DateLike,
        *,
        entities: Sequence[str] | None = None,
        window_weeks: int | None = None,
    ) -> list[NowcastObject]:
        """One :class:`NowcastObject` per entity per week in the nowcast window."""
        delay = self._require_delay_model()
        as_of_date = ensure_date(as_of)
        if as_of_date is None:
            raise ValueError("as_of must not be null.")
        window = int(window_weeks or self.window_weeks)
        keys = list(entities) if entities is not None else list(history.entities)

        reference_week = iso_week_start(as_of_date)
        w_now = history.week_position(reference_week)
        counts = history.counts_as_of(as_of_date)
        start = max(0, w_now - window + 1)
        weeks: list[date] = list(history.weeks[start: w_now + 1])
        if not weeks:
            return []

        rng = np.random.default_rng(self._seed + int(as_of_date.toordinal()))
        entity_positions = {key: i for i, key in enumerate(history.entities)}
        alpha_level = (1.0 - self.interval_level) / 2.0

        objects: list[NowcastObject] = []
        for key in keys:
            row = entity_positions.get(key)
            if row is None:
                continue
            country, disease = key.split("|")
            observed = counts[row, start: w_now + 1].astype(float)

            p = np.array(
                [delay.reporting_probability(week, as_of_date, disease, country) for week in weeks],
                dtype=float,
            )
            fit = delay.resolve_fit(disease, country)
            draws = self._entity_draws(
                observed=observed, p=p, n_delay_obs=int(fit.n_observations),
                country_iso3=country, disease=disease, rng=rng,
            )

            mc_mean = draws.mean(axis=1)
            mc_lower = np.quantile(draws, alpha_level, axis=1)
            mc_upper = np.quantile(draws, 1.0 - alpha_level, axis=1)

            # Borrow strength across weeks on the log scale.
            log_draws = np.log1p(draws)
            y = log_draws.mean(axis=1)
            obs_var = np.maximum(log_draws.var(axis=1) / max(draws.shape[1], 1), 1e-6)
            smoothed, _ = self._local_level_smoother(y, obs_var)
            central = np.maximum(np.expm1(smoothed), observed)

            # Keep the Monte-Carlo relative spread, shift to the smoothed centre.
            shift = np.where(mc_mean > 1e-9, central / np.maximum(mc_mean, 1e-9), 1.0)
            lower = np.maximum(mc_lower * shift, observed)
            upper = np.maximum(mc_upper * shift, central)

            expected_delay = float(max(delay.expected_delay(disease, country), 0.0))
            ascertainment_mean = self.ascertainment.mean(country, disease)

            for i, week in enumerate(weeks):
                latent = float(central[i])
                hidden = float(latent - observed[i])
                gap = float(np.clip(hidden / latent, 0.0, 1.0)) if latent > 1e-9 else 0.0
                width = float(upper[i] - lower[i])
                objects.append(
                    NowcastObject(
                        entity_key=key,
                        country_iso3=country,
                        disease=disease,
                        as_of=as_of_date,
                        reference_week=week,
                        observed_disease_burden=float(observed[i]),
                        reporting_probability=float(np.clip(p[i], 0.0, 1.0)),
                        expected_reporting_delay=expected_delay,
                        latent_disease_estimate=latent,
                        nowcast_lower=float(max(lower[i], 0.0)),
                        nowcast_upper=float(max(upper[i], lower[i])),
                        interval_level=self.interval_level,
                        estimated_hidden_burden=hidden,
                        reporting_gap=gap,
                        reporting_gap_band=band_for(gap, self._gap_bands, default="minor"),
                        ascertainment_mean=ascertainment_mean,
                        ascertainment_source=self.ascertainment.source,
                        method=self.method,
                        confidence=self._confidence(
                            p=float(p[i]), point=latent, width=width,
                            n_delay_obs=int(fit.n_observations),
                        ),
                        n_contributing_records=int(round(float(observed[i]))),
                    )
                )
        return objects

    @staticmethod
    def _confidence(*, p: float, point: float, width: float, n_delay_obs: int) -> float:
        """How much weight this estimate deserves, in [0, 1].

        Three things make a nowcast trustworthy: most of the week is already
        visible (``completeness``), the predictive interval is narrow relative
        to the estimate (``precision``), and the delay distribution behind it
        was fitted on a decent number of observations (``evidence``).
        """
        completeness = float(np.clip(p, 0.0, 1.0))
        precision = 1.0 / (1.0 + width / max(point, 1.0))
        evidence = n_delay_obs / (n_delay_obs + 50.0)
        return float(np.clip(0.50 * completeness + 0.30 * precision + 0.20 * evidence, 0.0, 1.0))

    # ------------------------------------------------------------------ #
    # tabular outputs
    # ------------------------------------------------------------------ #
    def nowcast_frame(
        self,
        history: OfficialHistory,
        as_of: DateLike,
        *,
        entities: Sequence[str] | None = None,
        window_weeks: int | None = None,
    ) -> pd.DataFrame:
        """Nowcast window as a tidy frame, with 4-week aggregates attached.

        The single-week estimate is the schema-defined quantity, but a
        4-week aggregate is a far more stable basis for ranking countries on
        the radar (one late notification can double a single week). Both are
        emitted; the app labels which is which.
        """
        objects = self.nowcast(
            history, as_of, entities=entities, window_weeks=window_weeks
        )
        if not objects:
            return pd.DataFrame(columns=NOWCAST_PANEL_COLUMNS)

        rows = [
            {
                "entity_key": o.entity_key,
                "country_iso3": o.country_iso3,
                "disease": o.disease,
                "as_of": pd.Timestamp(o.as_of),
                "reference_week": pd.Timestamp(o.reference_week),
                "observed_disease_burden": o.observed_disease_burden,
                "reporting_probability": o.reporting_probability,
                "expected_reporting_delay": o.expected_reporting_delay,
                "latent_disease_estimate": o.latent_disease_estimate,
                "nowcast_lower": o.nowcast_lower,
                "nowcast_upper": o.nowcast_upper,
                "interval_level": o.interval_level,
                "estimated_hidden_burden": o.estimated_hidden_burden,
                "reporting_gap": o.reporting_gap,
                "reporting_gap_band": o.reporting_gap_band,
                "ascertainment_mean": o.ascertainment_mean,
                "ascertainment_source": o.ascertainment_source,
                "method": o.method,
                "confidence": o.confidence,
                "n_contributing_records": o.n_contributing_records,
            }
            for o in objects
        ]
        frame = pd.DataFrame(rows)
        reference_week = pd.Timestamp(iso_week_start(ensure_date(as_of)))
        frame["is_reference_week"] = frame["reference_week"] == reference_week

        recent_cutoff = reference_week - pd.Timedelta(weeks=3)
        recent = frame.loc[frame["reference_week"] >= recent_cutoff]
        aggregate = (
            recent.groupby("entity_key", as_index=False)
            .agg(
                observed_4w=("observed_disease_burden", "sum"),
                latent_4w=("latent_disease_estimate", "sum"),
                hidden_4w=("estimated_hidden_burden", "sum"),
            )
        )
        aggregate["reporting_gap_4w"] = np.where(
            aggregate["latent_4w"] > 1e-9,
            np.clip(aggregate["hidden_4w"] / aggregate["latent_4w"].replace(0, np.nan), 0.0, 1.0),
            0.0,
        )
        aggregate["reporting_gap_4w"] = aggregate["reporting_gap_4w"].fillna(0.0)
        frame = frame.merge(aggregate, on="entity_key", how="left")
        return frame[NOWCAST_PANEL_COLUMNS].reset_index(drop=True)

    def reporting_estimates(
        self, entities: Sequence[str], as_of: DateLike
    ) -> list[ReportingEstimate]:
        """Fitted description of the observation process, per entity."""
        delay = self._require_delay_model()
        reference_week = iso_week_start(ensure_date(as_of))
        return [delay.estimate(key, as_of, reference_week) for key in entities]

    # ------------------------------------------------------------------ #
    # documentation
    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        delay = self.delay_model
        return {
            "model": "LatentStateNowcastModel",
            "method": self.method,
            "estimator": (
                "Negative-binomial posterior-predictive completion of the right-truncated "
                "reporting triangle (inverse-probability limit as the prior vanishes), "
                "divided by a prior ascertainment probability, smoothed across the window "
                "by a local-level state-space model."
            ),
            "prior_shape_a0": self.prior_shape,
            "prior_rate_b0": self.prior_rate,
            "window_weeks": self.window_weeks,
            "min_reporting_probability": self.min_p,
            "interval_level": self.interval_level,
            "monte_carlo_draws": self.n_draws,
            "uncertainty_sources": [
                "sampling of the not-yet-reported remainder",
                "estimation error in the reporting probability",
                "the ascertainment prior",
            ],
            "uncertainty_not_propagated": [
                "structural error in the delay distribution family",
                "any mismatch between the synthetic corpus and real reporting behaviour",
            ],
            "ascertainment": self.ascertainment.describe(),
            "delay_model": (
                {
                    "as_of": str(delay.as_of),
                    "n_groups": len(delay.fits),
                    "global_family": delay.fits.get(delay.GLOBAL_KEY).family
                    if delay.fits.get(delay.GLOBAL_KEY) else None,
                    "global_median_days": round(
                        float(delay.fits[delay.GLOBAL_KEY].median), 2
                    ) if delay.fits.get(delay.GLOBAL_KEY) else None,
                }
                if delay is not None else None
            ),
        }
