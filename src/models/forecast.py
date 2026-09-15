r"""Short-term probabilistic forecasts of officially reportable burden.

What is being forecast, precisely
---------------------------------
The target is ``target_reported_final``: the number of outbreaks with a
*reference week* inside the horizon that are **eventually** officially
reported. This choice is deliberate and it is the only one that can be honestly
scored. Forecasting "true latent burden" would produce a number that can never
be checked against anything; forecasting "burden visible at the target date"
would make the model learn the notification backlog rather than the epidemic.

The latent scale is still surfaced, but as an explicit, separately labelled
rescaling by the ascertainment prior (``forecast.report_latent_scale``), so the
assumption is never buried inside a headline figure.

Three members, three inductive biases
-------------------------------------
``negbin_glm``
    Negative-binomial log-link regression on the point-in-time design matrix
    (recent visible activity, seasonal climatology, neighbour activity,
    environmental suitability, host exposure, intelligence anomaly, reporting
    behaviour) plus Fourier seasonality on the target week. Strong when the
    covariates carry signal; it is the only member that can react to something
    that has not happened in this country before.

``damped_trend``
    Holt linear trend with damping :math:`\phi` on the ``log(1+y)`` scale of
    the vintage-visible series. Strong mid-epidemic, and the damping stops it
    extrapolating an exponential to the moon -- which matters, because an
    undamped trend fitted to the start of an HPAI season forecasts the
    extinction of European poultry by March.

``seasonal_climatology``
    Week-of-year mean from prior calendar years of the visible vintage. Strong
    in the off-season and for entities with little recent activity; it is also
    the member that keeps the ensemble from forecasting zero forever in a
    country that reports every winter.

Ensemble
--------
Members are weighted by out-of-sample CRPS on a validation window strictly
after ``forecast.train_end`` (see :func:`~src.models.ensemble.crps_weights`).
The predictive distribution is a genuine mixture -- draws are pooled in
proportion to the weights -- not an average of quantiles, which would
understate the spread exactly when the members disagree.

Every predictive quantity (median, mean, interval, exceedance probability) is
computed from the same pooled sample, so they cannot contradict each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.features.temporal import OfficialHistory
from src.models.baselines import CountGLM, SeasonalBaseline
from src.models.ensemble import crps_weights, equal_weights
from src.models.nowcast import AscertainmentPrior
from src.schemas.outputs import ForecastObject
from src.utils.config import AppConfig, get_config, load_diseases, load_thresholds
from src.utils.dates import DateLike, ensure_date, iso_week_start, seasonal_harmonics
from src.utils.logging_utils import get_logger
from src.utils.stats import EPS, crps_empirical, fit_nb_dispersion, nb_rvs, safe_log

LOGGER = get_logger(__name__)

__all__ = [
    "ForecastModel",
    "FORECAST_FEATURES",
    "FORECAST_PANEL_COLUMNS",
    "damped_trend_forecast",
]

#: Design-matrix columns the GLM member is allowed to use. A deliberate subset:
#: the full 65-column matrix over-fits a weekly count panel this size, and these
#: are the columns with a mechanistic reason to predict future burden.
FORECAST_FEATURES: tuple[str, ...] = (
    "obs_last_1w",
    "obs_last_4w",
    "obs_last_13w",
    "obs_ewma_z",
    "obs_weeks_since_last",
    "hist_seasonal_baseline_log",
    "hist_excess_over_baseline",
    "spa_neighbour_activity_4w",
    "spa_neighbour_active_share",
    "env_suitability_4w",
    "exp_host_density_log",
    "intel_fused_anomaly",
    "rep_reporting_probability",
)

FORECAST_PANEL_COLUMNS: list[str] = [
    "entity_key", "country_iso3", "disease", "as_of", "horizon_days", "target_week",
    "target", "point", "mean", "lower", "upper", "interval_level",
    "p_exceed_threshold", "exceedance_threshold", "p_increase", "p_new_outbreak",
    "method", "dispersion",
    "q05", "q10", "q25", "q50", "q75", "q90", "q95",
    "point_latent_scale", "lower_latent_scale", "upper_latent_scale", "ascertainment_mean",
]

_TREND_ALPHA = 0.35
_TREND_BETA = 0.15
_TREND_PHI = 0.85
_TREND_WINDOW_WEEKS = 52


# --------------------------------------------------------------------------- #
# damped trend
# --------------------------------------------------------------------------- #
def damped_trend_forecast(
    counts: np.ndarray,
    horizons_weeks: Sequence[int],
    *,
    alpha: float = _TREND_ALPHA,
    beta: float = _TREND_BETA,
    phi: float = _TREND_PHI,
) -> dict[int, np.ndarray]:
    """Holt damped-trend forecast on ``log(1+y)``, vectorised over entities.

    Parameters
    ----------
    counts:
        ``(n_entities, n_weeks)`` vintage-visible counts, most recent week last.
    horizons_weeks:
        Steps ahead to forecast.

    Returns
    -------
    ``{steps: mu}`` on the original count scale, floored at zero.
    """
    if counts.size == 0:
        return {int(h): np.zeros(counts.shape[0]) for h in horizons_weeks}

    y = safe_log(counts[:, -_TREND_WINDOW_WEEKS:])
    level = y[:, 0].copy()
    trend = np.zeros_like(level)
    for t in range(1, y.shape[1]):
        previous = level.copy()
        level = alpha * y[:, t] + (1.0 - alpha) * (level + phi * trend)
        trend = beta * (level - previous) + (1.0 - beta) * phi * trend

    out: dict[int, np.ndarray] = {}
    for steps in horizons_weeks:
        damping = np.sum([phi**i for i in range(1, int(steps) + 1)])
        out[int(steps)] = np.clip(np.expm1(np.clip(level + damping * trend, -20.0, 20.0)), 0.0, None)
    return out


# --------------------------------------------------------------------------- #
# fitted state
# --------------------------------------------------------------------------- #
@dataclass
class HorizonFit:
    """Everything fitted for one forecast horizon."""

    horizon_days: int
    glm: CountGLM | None = None
    dispersion: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    validation_crps: dict[str, float] = field(default_factory=dict)
    n_train: int = 0
    n_validation: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "n_train": self.n_train,
            "n_validation": self.n_validation,
            "ensemble_weights": self.weights,
            "validation_crps": {k: (None if not np.isfinite(v) else round(v, 4))
                                for k, v in self.validation_crps.items()},
            "dispersion_alpha": {k: round(v, 4) for k, v in self.dispersion.items()},
            "glm": self.glm.describe() if self.glm is not None else None,
        }


class ForecastModel:
    """CRPS-weighted negative-binomial ensemble over 7/14/28-day horizons."""

    method = "crps_weighted_nb_ensemble_v1"

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.horizons: list[int] = list(self.config.forecast_days)
        self.members: list[str] = [
            str(m) for m in self.config.get(
                "forecast.members", ["negbin_glm", "damped_trend", "seasonal_climatology"]
            )
        ]
        self.min_weight = float(self.config.get("forecast.min_weight", 0.05))
        self.train_end = ensure_date(self.config.get("forecast.train_end", "2024-06-30"))
        self.quantile_levels = list(self.config.quantiles)
        self.interval_level = float(self.config.central_interval)
        self.n_draws = int(self.config.mc_draws)
        self.target_name = str(self.config.get("forecast.target", "reported_final"))
        self.report_latent_scale = bool(self.config.get("forecast.report_latent_scale", True))

        thresholds = load_thresholds()
        questions = thresholds.get("forecast_questions", {}) or {}
        self.exceedance_multipliers = [
            float(m) for m in questions.get("exceedance_multipliers", [1.0, 2.0])
        ]
        self.increase_margin = float(questions.get("increase_relative_margin", 0.10))
        self.new_outbreak_min = int(questions.get("new_outbreak_min_count", 1))

        self._diseases = load_diseases()
        self._ascertainment = AscertainmentPrior(self.config)
        self._climatology = SeasonalBaseline()
        self.fits: dict[int, HorizonFit] = {}
        self._seed = int(self.config.random_seed)

    # ------------------------------------------------------------------ #
    # member means
    # ------------------------------------------------------------------ #
    def _glm_frame(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Design columns plus Fourier seasonality on the target week."""
        available = [c for c in FORECAST_FEATURES if c in panel.columns]
        frame = panel[available].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        harmonics = seasonal_harmonics(panel["target_week"].tolist(), n_harmonics=2)
        harmonics.index = frame.index
        # Log-transform the count-scale predictors: burden responds
        # multiplicatively, and an untransformed lag lets one outlier week
        # dominate the fit.
        for column in ("obs_last_1w", "obs_last_4w", "obs_last_13w"):
            if column in frame.columns:
                frame[column] = np.log1p(frame[column].clip(lower=0.0))
        return pd.concat([frame, harmonics], axis=1)

    def _structural_means(
        self,
        history: OfficialHistory,
        as_of_dates: Sequence[date],
        horizons: Sequence[int],
    ) -> pd.DataFrame:
        """``damped_trend`` and ``seasonal_climatology`` means for a set of as-ofs.

        Computed once per as-of date (both members need the reconstructed
        vintage, which is the expensive part) and returned long by
        ``(entity_key, as_of, horizon_days)``.
        """
        rows: list[pd.DataFrame] = []
        for as_of in as_of_dates:
            as_of_date = ensure_date(as_of)
            w_now = history.week_position(iso_week_start(as_of_date))
            counts = history.counts_as_of(as_of_date)[:, : w_now + 1]
            steps = {int(h): max(int(round(int(h) / 7)), 1) for h in horizons}
            trend = damped_trend_forecast(counts, sorted(set(steps.values())))
            for horizon in horizons:
                target_week = iso_week_start(as_of_date + timedelta(days=int(horizon)))
                climatology = self._climatology.expected(history, as_of_date, target_week)
                rows.append(
                    pd.DataFrame(
                        {
                            "entity_key": history.entities,
                            "as_of": pd.Timestamp(as_of_date),
                            "horizon_days": int(horizon),
                            "mu_damped_trend": trend[steps[int(horizon)]],
                            "mu_seasonal_climatology": climatology,
                        }
                    )
                )
        if not rows:
            return pd.DataFrame(
                columns=["entity_key", "as_of", "horizon_days",
                         "mu_damped_trend", "mu_seasonal_climatology"]
            )
        return pd.concat(rows, ignore_index=True)

    # ------------------------------------------------------------------ #
    # fitting
    # ------------------------------------------------------------------ #
    def fit(
        self,
        design: pd.DataFrame,
        targets: pd.DataFrame,
        history: OfficialHistory,
    ) -> ForecastModel:
        """Fit every member and learn the ensemble weights by validation CRPS."""
        panel = self._assemble_training_panel(design, targets, history)
        if panel.empty:
            raise ValueError(
                "Forecast training panel is empty. Check that build_features.py produced "
                "forecast_targets.parquet with target_complete rows."
            )

        rng = np.random.default_rng(self._seed)
        for horizon in self.horizons:
            block = panel.loc[panel["horizon_days"] == int(horizon)].copy()
            train = block.loc[block["as_of"] <= pd.Timestamp(self.train_end)]
            validation = block.loc[block["as_of"] > pd.Timestamp(self.train_end)]
            fit = HorizonFit(
                horizon_days=int(horizon),
                n_train=int(len(train)),
                n_validation=int(len(validation)),
            )

            if train.empty:
                LOGGER.warning(
                    "Horizon %sd has no training rows at or before %s; using equal weights.",
                    horizon, self.train_end,
                )
                fit.weights = equal_weights(self.members)
                fit.dispersion = {name: 0.5 for name in self.members}
                self.fits[int(horizon)] = fit
                continue

            y_train = train["target_reported_final"].to_numpy(dtype=float)

            # --- member 1: NB GLM on the design matrix --------------------- #
            if "negbin_glm" in self.members:
                glm = CountGLM(family="negbin", ridge=2.0)
                glm.fit(self._glm_frame(train), y_train)
                fit.glm = glm
                fit.dispersion["negbin_glm"] = float(glm.alpha_)

            # --- members 2 and 3: dispersion from training residuals ------- #
            for name, column in (
                ("damped_trend", "mu_damped_trend"),
                ("seasonal_climatology", "mu_seasonal_climatology"),
            ):
                if name not in self.members:
                    continue
                mu = np.clip(train[column].to_numpy(dtype=float), EPS, None)
                fit.dispersion[name] = float(fit_nb_dispersion(y_train, mu))

            # --- ensemble weights from validation CRPS --------------------- #
            if validation.empty:
                LOGGER.warning(
                    "Horizon %sd has no validation rows after %s; using equal weights.",
                    horizon, self.train_end,
                )
                fit.weights = equal_weights(self.members)
                fit.validation_crps = {name: float("nan") for name in self.members}
            else:
                y_valid = validation["target_reported_final"].to_numpy(dtype=float)
                for name in self.members:
                    mu = self._member_mu(name, validation, fit)
                    fit.validation_crps[name] = self._mean_crps(
                        mu, fit.dispersion.get(name, 0.5), y_valid, rng
                    )
                fit.weights = crps_weights(
                    fit.validation_crps, min_weight=self.min_weight
                )

            self.fits[int(horizon)] = fit
            LOGGER.info(
                "Forecast %sd | train=%s valid=%s | CRPS %s | weights %s",
                horizon, fit.n_train, fit.n_validation,
                {k: (None if not np.isfinite(v) else round(v, 3))
                 for k, v in fit.validation_crps.items()},
                fit.weights,
            )
        return self

    def _assemble_training_panel(
        self, design: pd.DataFrame, targets: pd.DataFrame, history: OfficialHistory
    ) -> pd.DataFrame:
        """Join design matrix, targets and structural member means."""
        target_frame = targets.copy()
        target_frame["as_of"] = pd.to_datetime(target_frame["as_of"])
        target_frame["target_week"] = pd.to_datetime(target_frame["target_week"])
        target_frame = target_frame.loc[target_frame["target_complete"].astype(bool)]
        target_frame = target_frame.loc[target_frame["horizon_days"].isin(self.horizons)]

        design_frame = design.copy()
        design_frame["as_of"] = pd.to_datetime(design_frame["as_of"])

        panel = target_frame.merge(
            design_frame, on=["entity_key", "as_of"], how="inner", suffixes=("", "_design")
        )
        as_of_dates = sorted({ts.date() for ts in panel["as_of"].unique()})
        structural = self._structural_means(history, as_of_dates, self.horizons)
        panel = panel.merge(structural, on=["entity_key", "as_of", "horizon_days"], how="left")
        panel["mu_damped_trend"] = panel["mu_damped_trend"].fillna(0.0)
        panel["mu_seasonal_climatology"] = panel["mu_seasonal_climatology"].fillna(0.0)
        LOGGER.info(
            "Forecast panel: %s rows across %s as-of dates and %s horizons",
            len(panel), len(as_of_dates), panel["horizon_days"].nunique(),
        )
        return panel

    def _member_mu(self, name: str, block: pd.DataFrame, fit: HorizonFit) -> np.ndarray:
        if name == "negbin_glm":
            if fit.glm is None:
                return np.zeros(len(block))
            return fit.glm.predict(self._glm_frame(block))
        if name == "damped_trend":
            return np.clip(block["mu_damped_trend"].to_numpy(dtype=float), 0.0, None)
        if name == "seasonal_climatology":
            return np.clip(block["mu_seasonal_climatology"].to_numpy(dtype=float), 0.0, None)
        raise KeyError(f"Unknown forecast member: {name!r}")

    def _mean_crps(
        self,
        mu: np.ndarray,
        alpha: float,
        y: np.ndarray,
        rng: np.random.Generator,
        *,
        n_draws: int = 300,
    ) -> float:
        """Mean CRPS of an NB predictive distribution over a validation block."""
        if mu.size == 0:
            return float("nan")
        draws = nb_rvs(mu[:, None], alpha, size=(mu.size, n_draws), rng=rng).astype(float)
        scores = [crps_empirical(draws[i], float(y[i])) for i in range(mu.size)]
        finite = [s for s in scores if np.isfinite(s)]
        return float(np.mean(finite)) if finite else float("nan")

    # ------------------------------------------------------------------ #
    # prediction
    # ------------------------------------------------------------------ #
    def predict(
        self,
        as_of: DateLike,
        history: OfficialHistory,
        design_at_as_of: pd.DataFrame,
        *,
        current_level: pd.Series | None = None,
        entities: Sequence[str] | None = None,
    ) -> list[ForecastObject]:
        """Forecast every entity at every horizon for one as-of date.

        Parameters
        ----------
        design_at_as_of:
            The design-matrix rows for exactly this as-of date.
        current_level:
            Per-entity reference level used by ``p_increase`` -- normally the
            nowcast central estimate for the reference week, which is the
            operationally meaningful comparator ("worse than now", not "worse
            than what has been filed so far").
        """
        if not self.fits:
            raise RuntimeError("ForecastModel.predict called before fit().")
        as_of_date = ensure_date(as_of)
        keys = list(entities) if entities is not None else list(design_at_as_of["entity_key"])
        if not keys:
            return []

        base = design_at_as_of.loc[design_at_as_of["entity_key"].isin(keys)].copy()
        base["as_of"] = pd.to_datetime(as_of_date)
        base = base.set_index("entity_key").reindex(keys).reset_index()

        structural = self._structural_means(history, [as_of_date], self.horizons)
        rng = np.random.default_rng(self._seed + int(as_of_date.toordinal()))
        alpha_tail = (1.0 - self.interval_level) / 2.0

        level = (
            current_level.reindex(keys).astype(float).fillna(0.0)
            if current_level is not None
            else pd.Series(0.0, index=keys)
        )

        objects: list[ForecastObject] = []
        for horizon in self.horizons:
            fit = self.fits.get(int(horizon))
            if fit is None:
                continue
            target_week = iso_week_start(as_of_date + timedelta(days=int(horizon)))
            block = base.copy()
            block["horizon_days"] = int(horizon)
            block["target_week"] = pd.Timestamp(target_week)
            block = block.merge(
                structural.loc[structural["horizon_days"] == int(horizon)],
                on=["entity_key", "as_of", "horizon_days"], how="left",
            )
            block["mu_damped_trend"] = block["mu_damped_trend"].fillna(0.0)
            block["mu_seasonal_climatology"] = block["mu_seasonal_climatology"].fillna(0.0)

            pooled = self._mixture_draws(block, fit, rng)
            quantiles = np.quantile(pooled, self.quantile_levels, axis=1).T
            median = np.quantile(pooled, 0.5, axis=1)
            mean = pooled.mean(axis=1)
            lower = np.quantile(pooled, alpha_tail, axis=1)
            upper = np.quantile(pooled, 1.0 - alpha_tail, axis=1)

            for i, key in enumerate(block["entity_key"].tolist()):
                country, disease = key.split("|")
                spec = self._diseases.get(disease)
                threshold = (
                    float(spec.exceedance_threshold_weekly) * self.exceedance_multipliers[0]
                    if spec is not None else 5.0
                )
                draws = pooled[i]
                reference = float(level.get(key, 0.0)) * (1.0 + self.increase_margin)

                objects.append(
                    ForecastObject(
                        entity_key=key,
                        country_iso3=country,
                        disease=disease,
                        as_of=as_of_date,
                        horizon_days=int(horizon),
                        target_week=target_week,
                        target="reported",
                        point=float(max(median[i], 0.0)),
                        mean=float(max(mean[i], 0.0)),
                        lower=float(max(lower[i], 0.0)),
                        upper=float(max(upper[i], lower[i])),
                        interval_level=self.interval_level,
                        quantiles={
                            f"q{int(round(q * 100)):02d}": float(quantiles[i, j])
                            for j, q in enumerate(self.quantile_levels)
                        },
                        p_exceed_threshold=float(np.mean(draws > threshold)),
                        exceedance_threshold=threshold,
                        p_increase=float(np.mean(draws > reference)),
                        p_new_outbreak=float(np.mean(draws >= self.new_outbreak_min)),
                        method=self.method,
                        ensemble_weights=dict(fit.weights),
                        dispersion=float(
                            np.mean([fit.dispersion.get(m, 0.5) for m in self.members])
                        ),
                    )
                )
        return objects

    def _mixture_draws(
        self, block: pd.DataFrame, fit: HorizonFit, rng: np.random.Generator
    ) -> np.ndarray:
        """Pooled draws from the weighted mixture of member predictives."""
        n_rows = len(block)
        weights = fit.weights or equal_weights(self.members)
        pieces: list[np.ndarray] = []
        for name in self.members:
            weight = float(weights.get(name, 0.0))
            if weight <= 0:
                continue
            take = max(int(round(weight * self.n_draws)), 1)
            mu = np.clip(self._member_mu(name, block, fit), 0.0, None)
            pieces.append(
                nb_rvs(mu[:, None], fit.dispersion.get(name, 0.5), size=(n_rows, take), rng=rng)
                .astype(float)
            )
        if not pieces:
            return np.zeros((n_rows, 1))
        return np.concatenate(pieces, axis=1)

    def predict_frame(
        self,
        as_of: DateLike,
        history: OfficialHistory,
        design_at_as_of: pd.DataFrame,
        *,
        current_level: pd.Series | None = None,
        entities: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Multi-horizon forecasts as a tidy frame, including the latent rescaling."""
        objects = self.predict(
            as_of, history, design_at_as_of,
            current_level=current_level, entities=entities,
        )
        if not objects:
            return pd.DataFrame(columns=FORECAST_PANEL_COLUMNS)

        rows: list[dict[str, Any]] = []
        for o in objects:
            country, disease = o.entity_key.split("|")
            ascertainment = self._ascertainment.mean(country, disease)
            scale = 1.0 / max(ascertainment, 1e-6) if self.report_latent_scale else 1.0
            row: dict[str, Any] = {
                "entity_key": o.entity_key,
                "country_iso3": o.country_iso3,
                "disease": o.disease,
                "as_of": pd.Timestamp(o.as_of),
                "horizon_days": o.horizon_days,
                "target_week": pd.Timestamp(o.target_week),
                "target": o.target,
                "point": o.point,
                "mean": o.mean,
                "lower": o.lower,
                "upper": o.upper,
                "interval_level": o.interval_level,
                "p_exceed_threshold": o.p_exceed_threshold,
                "exceedance_threshold": o.exceedance_threshold,
                "p_increase": o.p_increase,
                "p_new_outbreak": o.p_new_outbreak,
                "method": o.method,
                "dispersion": o.dispersion,
                "point_latent_scale": o.point * scale,
                "lower_latent_scale": o.lower * scale,
                "upper_latent_scale": o.upper * scale,
                "ascertainment_mean": ascertainment,
            }
            for level in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95):
                key = f"q{int(round(level * 100)):02d}"
                row[key] = o.quantiles.get(key, np.nan)
            rows.append(row)
        return pd.DataFrame(rows)[FORECAST_PANEL_COLUMNS].reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # documentation
    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        return {
            "model": "ForecastModel",
            "method": self.method,
            "target": (
                "target_reported_final: outbreaks with a reference week in the horizon "
                "that are EVENTUALLY officially reported (a scorable observable)."
            ),
            "latent_scale_reported_separately": self.report_latent_scale,
            "members": self.members,
            "horizons_days": self.horizons,
            "train_end": str(self.train_end),
            "weighting": "softmax on negative normalised validation CRPS, floored at min_weight",
            "min_weight": self.min_weight,
            "predictive_distribution": "pooled negative-binomial mixture over members",
            "monte_carlo_draws": self.n_draws,
            "glm_features": list(FORECAST_FEATURES) + ["sin_1", "cos_1", "sin_2", "cos_2"],
            "damped_trend": {"alpha": _TREND_ALPHA, "beta": _TREND_BETA, "phi": _TREND_PHI,
                             "window_weeks": _TREND_WINDOW_WEEKS},
            "horizons": {str(h): fit.to_dict() for h, fit in sorted(self.fits.items())},
        }
