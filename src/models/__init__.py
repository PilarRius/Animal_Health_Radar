"""Models: the observation process, the latent state, the risk and the horizon.

Four questions, four model families, deliberately separate:

:mod:`src.models.delay`
    *How does information arrive?* Right-truncation-corrected, partially pooled
    reporting-delay distributions. This is the observation process, estimated
    rather than assumed.

:mod:`src.models.nowcast`
    *What is happening now, and how much of it is invisible?*
    Negative-binomial completion of the reporting triangle, divided by an
    explicit ascertainment prior, smoothed by a local-level state-space model.

:mod:`src.models.early_warning`
    *Should someone look at this?* Calibrated gradient boosting on the
    point-in-time design matrix, with computed explanations and family-level
    counterfactual ablations.

:mod:`src.models.forecast`
    *Where is this going?* CRPS-weighted negative-binomial ensemble over
    7/14/28-day horizons.

Supporting modules: :mod:`src.models.baselines` (the competitors that have to
be beaten), :mod:`src.models.calibration` (probabilities that mean what they
say) and :mod:`src.models.ensemble` (combination without obfuscation).

Attribute access is lazy. :mod:`src.features.build` imports the delay model,
and the model modules import the feature contract from
:mod:`src.features.build`; resolving the names on first use rather than at
package import keeps that cycle from depending on which module a caller
happened to import first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    # delay / observation process
    "DelayFit",
    "ReportingDelayModel",
    # nowcast
    "AscertainmentPrior",
    "LatentStateNowcastModel",
    "NOWCAST_PANEL_COLUMNS",
    # early warning
    "EarlyWarningModel",
    "TemporalSplit",
    # forecast
    "ForecastModel",
    "FORECAST_FEATURES",
    "FORECAST_PANEL_COLUMNS",
    "damped_trend_forecast",
    # baselines
    "CUSUMDetector",
    "CountGLM",
    "EARLY_WARNING_BASELINES",
    "EWMAAnomalyDetector",
    "HeuristicBaseline",
    "OFFICIAL_ONLY_FEATURES",
    "OfficialRecordOnlyBaseline",
    "SeasonalBaseline",
    "control_chart_panel",
    # calibration
    "CalibrationReport",
    "Calibrator",
    "calibration_report",
    "classification_metrics",
    "fit_calibrator",
    "precision_at_k",
    "reliability_table",
    # ensemble
    "ScoreStacker",
    "crps_weights",
    "rank_average",
]

_EXPORTS: dict[str, str] = {
    "DelayFit": "src.models.delay",
    "ReportingDelayModel": "src.models.delay",
    "AscertainmentPrior": "src.models.nowcast",
    "LatentStateNowcastModel": "src.models.nowcast",
    "NOWCAST_PANEL_COLUMNS": "src.models.nowcast",
    "EarlyWarningModel": "src.models.early_warning",
    "TemporalSplit": "src.models.early_warning",
    "ForecastModel": "src.models.forecast",
    "FORECAST_FEATURES": "src.models.forecast",
    "FORECAST_PANEL_COLUMNS": "src.models.forecast",
    "damped_trend_forecast": "src.models.forecast",
    "CUSUMDetector": "src.models.baselines",
    "CountGLM": "src.models.baselines",
    "EARLY_WARNING_BASELINES": "src.models.baselines",
    "EWMAAnomalyDetector": "src.models.baselines",
    "HeuristicBaseline": "src.models.baselines",
    "OFFICIAL_ONLY_FEATURES": "src.models.baselines",
    "OfficialRecordOnlyBaseline": "src.models.baselines",
    "SeasonalBaseline": "src.models.baselines",
    "control_chart_panel": "src.models.baselines",
    "CalibrationReport": "src.models.calibration",
    "Calibrator": "src.models.calibration",
    "calibration_report": "src.models.calibration",
    "classification_metrics": "src.models.calibration",
    "fit_calibrator": "src.models.calibration",
    "precision_at_k": "src.models.calibration",
    "reliability_table": "src.models.calibration",
    "ScoreStacker": "src.models.ensemble",
    "crps_weights": "src.models.ensemble",
    "rank_average": "src.models.ensemble",
}


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:  # pragma: no cover - static analysis only
    from src.models.baselines import (
        EARLY_WARNING_BASELINES,
        OFFICIAL_ONLY_FEATURES,
        CountGLM,
        CUSUMDetector,
        EWMAAnomalyDetector,
        HeuristicBaseline,
        OfficialRecordOnlyBaseline,
        SeasonalBaseline,
        control_chart_panel,
    )
    from src.models.calibration import (
        CalibrationReport,
        Calibrator,
        calibration_report,
        classification_metrics,
        fit_calibrator,
        precision_at_k,
        reliability_table,
    )
    from src.models.delay import DelayFit, ReportingDelayModel
    from src.models.early_warning import EarlyWarningModel, TemporalSplit
    from src.models.ensemble import ScoreStacker, crps_weights, rank_average
    from src.models.forecast import (
        FORECAST_FEATURES,
        FORECAST_PANEL_COLUMNS,
        ForecastModel,
        damped_trend_forecast,
    )
    from src.models.nowcast import (
        NOWCAST_PANEL_COLUMNS,
        AscertainmentPrior,
        LatentStateNowcastModel,
    )
