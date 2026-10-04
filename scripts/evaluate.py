"""Evaluation artefacts for the trained models.

::

    python scripts/evaluate.py
"""

from __future__ import annotations

from typing import Any

import _bootstrap  # noqa: F401
import pandas as pd

from src.evaluation.timeliness import lead_time_report
from src.utils.config import get_config
from src.utils.io import read_json, read_parquet, write_json, write_parquet
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.evaluate")


def run() -> dict[str, Any]:
    config = get_config()
    processed = config.path("data_processed")
    models = config.path("models")
    interim = config.path("data_interim")
    validation = ensure_dir(config.path("validation"))

    metrics: dict[str, Any] = {
        "data_mode": config.data_mode,
        "data_cutoff": config.data_cutoff.isoformat(),
        "caveat": (
            "Pilot mode: official observation is real WAHIS INFUR (offline extract). "
            "SMR provides semester status covariates. Media/env enrichment may still "
            "use labelled sample files — do not over-claim real-world lead time from intel."
            if config.data_mode in {"pilot", "offline"}
            else "Metrics on the synthetic sample corpus demonstrate methodology only."
        ),
    }

    ew_path = models / "early_warning_metrics.json"
    if ew_path.exists():
        metrics["early_warning"] = read_json(ew_path)

    baselines = models / "early_warning_baselines.json"
    if baselines.exists():
        metrics["early_warning_baselines"] = read_json(baselines)

    fc_path = models / "forecast_meta.json"
    if fc_path.exists():
        metrics["forecast"] = read_json(fc_path)

    delay_path = models / "delay_summary.parquet"
    if delay_path.exists():
        delay = read_parquet(delay_path)
        metrics["reporting_delay"] = delay.to_dict(orient="records")

    train_manifest = processed / "train_manifest.json"
    if train_manifest.exists():
        metrics["train_manifest"] = read_json(train_manifest)

    predictions = processed / "predictions.parquet"
    pred = None
    if predictions.exists():
        pred = read_parquet(predictions)
        metrics["predictions_summary"] = {
            "n_rows": int(len(pred)),
            "n_countries": int(pred["country"].nunique()),
            "n_diseases": int(pred["disease"].nunique()),
            "as_of_min": str(pred["as_of_date"].min()),
            "as_of_max": str(pred["as_of_date"].max()),
            "mean_ew_probability": float(pred["early_warning_probability"].mean()),
            "mean_reporting_gap": float(pred["reporting_gap"].mean()),
            "mean_reporting_probability": float(pred["reporting_probability"].mean()),
            "p50_reporting_probability": float(pred["reporting_probability"].median()),
            "mean_latent": float(pred["latent_mean"].mean()),
            "mean_observed": float(pred["observed"].mean()),
        }

    canonical_path = interim / "canonical_events.parquet"
    if pred is not None and canonical_path.exists():
        canonical = read_parquet(canonical_path)
        lead = lead_time_report(pred, canonical)
        metrics["lead_time"] = {k: v for k, v in lead.items() if k != "cases"}
        write_json(lead, validation / "lead_time.json")
        if lead.get("cases"):
            write_parquet(pd.DataFrame(lead["cases"]), validation / "lead_time_cases.parquet")

    write_json(metrics, validation / "metrics.json")
    try:
        ew_block = metrics.get("early_warning", {})
        # support both nested shapes
        test_metrics = (
            ew_block.get("test")
            or ew_block.get("metrics", {}).get("test")
            or {}
        )
        if isinstance(test_metrics, dict) and test_metrics:
            pd.DataFrame([test_metrics]).to_csv(validation / "metrics.csv", index=False)
    except Exception:  # noqa: BLE001
        pass

    LOGGER.info("Wrote evaluation artefacts to %s", validation)
    return metrics


def main() -> None:
    setup_logging()
    run()


if __name__ == "__main__":
    main()
