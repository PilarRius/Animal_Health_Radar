"""Evaluation artefacts for the trained models.

::

    python scripts/evaluate.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
import pandas as pd

from src.utils.config import get_config
from src.utils.io import read_json, read_parquet, write_json
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.evaluate")


def run() -> dict[str, Any]:
    config = get_config()
    processed = config.path("data_processed")
    models = config.path("models")
    validation = ensure_dir(config.path("validation"))

    metrics: dict[str, Any] = {
        "data_mode": config.data_mode,
        "caveat": (
            "Metrics on the synthetic sample corpus demonstrate methodology. "
            "They are not claims about real-world WAHIS performance."
        ),
    }

    ew_path = models / "early_warning_metrics.json"
    if ew_path.exists():
        metrics["early_warning"] = read_json(ew_path)

    fc_path = models / "forecast_meta.json"
    if fc_path.exists():
        metrics["forecast"] = read_json(fc_path)

    train_manifest = processed / "train_manifest.json"
    if train_manifest.exists():
        metrics["train_manifest"] = read_json(train_manifest)

    predictions = processed / "predictions.parquet"
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
        }

    write_json(metrics, validation / "metrics.json")
    # Flat CSV of EW test metrics if present
    try:
        test_metrics = metrics.get("early_warning", {}).get("metrics", {}).get("test", {})
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
