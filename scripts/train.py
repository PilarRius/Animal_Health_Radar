"""Stage 3 - train models and emit Shiny-ready prediction tables.

::

    python scripts/train.py
    python scripts/train.py --app-as-of-only   # score only the app as-of grid
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

import _bootstrap  # noqa: F401
import pandas as pd

from src.alerts import build_alerts
from src.features.temporal import OfficialHistory
from src.models.delay import ReportingDelayModel
from src.models.early_warning import EarlyWarningModel
from src.models.forecast import ForecastModel
from src.models.nowcast import LatentStateNowcastModel
from src.utils.config import get_config, load_countries, load_diseases
from src.utils.dates import date_range_days, week_starts_between
from src.utils.io import read_parquet, save_pickle, write_json, write_parquet
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.train")


def entity_grid() -> list[str]:
    return [f"{iso}|{code}" for iso in load_countries() for code in load_diseases()]


def app_as_of_dates(config) -> list[date]:
    start = config.get("time.as_of_grid.start", "2023-01-02")
    end = config.get("time.as_of_grid.end", config.data_cutoff)
    step = int(config.get("time.as_of_grid.step_days", 7))
    return date_range_days(start, end, step=step)


def run(*, app_as_of_only: bool = False, limit_entities: int | None = None, n_as_of: int = 52) -> dict[str, Any]:
    config = get_config()
    processed = ensure_dir(config.path("data_processed"))
    models_dir = ensure_dir(config.path("models"))
    interim = config.path("data_interim")

    design = read_parquet(processed / "design_matrix.parquet")
    labels = read_parquet(processed / "early_warning_labels.parquet")
    targets = read_parquet(processed / "forecast_targets.parquet")
    triangle = read_parquet(interim / "reporting_triangle.parquet")
    canonical = read_parquet(interim / "canonical_events.parquet")

    # Harmonise as_of types for merges
    for frame in (design, labels, targets):
        frame["as_of"] = pd.to_datetime(frame["as_of"])

    history = OfficialHistory(
        triangle,
        entities=entity_grid(),
        weeks=week_starts_between(config.start_date, config.end_date),
    )

    LOGGER.info("Stage 3a | reporting delay model @ data_cutoff")
    delay = ReportingDelayModel(config=config)
    delay.fit(canonical, as_of=config.data_cutoff)
    write_parquet(delay.summary(), models_dir / "delay_summary.parquet")
    save_pickle(delay, models_dir / "delay_model.pkl")

    LOGGER.info("Stage 3b | early-warning model")
    ew = EarlyWarningModel(config=config)
    ew.fit(design, labels)
    save_pickle(ew, models_dir / "early_warning_model.pkl")
    write_json(ew.describe(), models_dir / "early_warning_metrics.json")
    write_parquet(ew.feature_importance(), models_dir / "early_warning_importance.parquet")

    LOGGER.info("Stage 3c | forecast ensemble")
    fc = ForecastModel(config=config)
    fc.fit(design, targets, history)
    save_pickle(fc, models_dir / "forecast_model.pkl")
    write_json(
        {
            "fits": {
                str(h): {"weights": f.weights, "validation_crps": f.validation_crps}
                for h, f in fc.fits.items()
            }
        },
        models_dir / "forecast_meta.json",
    )

    nowcast = LatentStateNowcastModel(delay_model=delay, config=config)

    score_dates = app_as_of_dates(config)
    available = set(pd.to_datetime(design["as_of"]).dt.date)
    if app_as_of_only:
        score_dates = [d for d in score_dates if d in available]
        if not score_dates:
            score_dates = sorted(available)[-max(n_as_of, 1):]
        else:
            score_dates = score_dates[-max(n_as_of, 1):]
    else:
        score_dates = [d for d in score_dates if d in available] or sorted(available)[-max(n_as_of, 1):]

    LOGGER.info("Stage 3d | scoring %s as-of dates", len(score_dates))
    score_design = design.loc[pd.to_datetime(design["as_of"]).dt.date.isin(set(score_dates))].copy()
    if limit_entities:
        keys = sorted(score_design["entity_key"].unique())[:limit_entities]
        score_design = score_design.loc[score_design["entity_key"].isin(keys)]

    predictions, alerts, explanations = build_alerts(
        score_design,
        ew,
        nowcast,
        fc,
        history,
        as_of_dates=score_dates,
        model_version=str(config.get("project.version", "0.1.0")),
    )

    write_parquet(predictions, processed / "predictions.parquet")
    write_parquet(alerts, processed / "alerts.parquet")
    write_json({"explanations": explanations}, processed / "explanations.json")

    latest = score_dates[-1]
    nowcast_panel = nowcast.nowcast_frame(history, latest)
    write_parquet(nowcast_panel, processed / "nowcast_latest.parquet")

    manifest = {
        "stage": "train",
        "model_version": config.get("project.version", "0.1.0"),
        "n_predictions": int(len(predictions)),
        "n_alerts": int(len(alerts)),
        "as_of_first": str(score_dates[0]) if score_dates else None,
        "as_of_last": str(score_dates[-1]) if score_dates else None,
        "early_warning_metrics": {
            name: report.metrics for name, report in ew.reports_.items()
        },
        "forecast_weights": {
            str(h): f.weights for h, f in fc.fits.items()
        },
        "data_mode": config.data_mode,
    }
    write_json(manifest, processed / "train_manifest.json")
    LOGGER.info("Stage 3 complete | %s", json.dumps({k: manifest[k] for k in ("n_predictions", "as_of_last")}, default=str))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-as-of-only", action="store_true")
    parser.add_argument(
        "--n-as-of",
        type=int,
        default=52,
        help="When scoring the app grid, keep the most recent N as-of dates (default 52).",
    )
    parser.add_argument("--limit-entities", type=int, default=None)
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()
    setup_logging(args.log_level)
    run(
        app_as_of_only=args.app_as_of_only,
        limit_entities=args.limit_entities,
        n_as_of=args.n_as_of,
    )


if __name__ == "__main__":
    main()
