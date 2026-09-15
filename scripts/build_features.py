"""Stage 2 - point-in-time feature store and design matrix.

::

    python scripts/build_features.py

What it does
------------
1. Builds the feature store from the intelligence signals, environmental
   covariates and exposure layers, each row carrying its own availability date.
2. Builds the :class:`~src.features.temporal.OfficialHistory` reporting
   triangle, which can reconstruct the officially visible series for any date.
3. Walks an as-of grid and assembles one design matrix per date. Every row is
   built under its own knowledge cut-off, so the resulting training panel is
   point-in-time correct by construction rather than by inspection.
4. Attaches the early-warning labels and the forecast targets, which *are*
   allowed to use later data because they are outcomes, not inputs.

Outputs land in ``data/processed/``.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import _bootstrap  # noqa: F401
import pandas as pd

from src.features import (
    FeatureAssembler,
    FeatureStore,
    OfficialHistory,
    build_early_warning_labels,
    build_environmental_features,
    build_exposure_features,
    build_forecast_targets,
    build_intelligence_features,
)
from src.utils.config import get_config, load_countries, load_diseases
from src.utils.dates import date_range_days, week_starts_between
from src.utils.io import read_parquet, write_json, write_parquet
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.build_features")


def entity_grid() -> list[str]:
    """Every country x disease combination in the configured panel."""
    return [f"{iso}|{code}" for iso in load_countries() for code in load_diseases()]


def build_store(interim) -> FeatureStore:
    """Assemble the point-in-time feature store from the interim tables."""
    signals = read_parquet(interim / "signals.parquet")
    covariates = read_parquet(interim / "covariates.parquet")

    store = FeatureStore()
    blocks = {
        "intelligence": build_intelligence_features(signals),
        "environmental": build_environmental_features(covariates),
        "livestock_exposure": build_exposure_features(covariates),
    }
    for name, frame in blocks.items():
        if frame is None or frame.empty:
            LOGGER.warning("Feature family '%s' produced no rows.", name)
            continue
        store.add(frame)
    LOGGER.info("Feature store: %s", store)
    return store


def build_history(interim, config) -> OfficialHistory:
    """Reporting triangle over the full configured entity x week grid."""
    triangle = read_parquet(interim / "reporting_triangle.parquet")
    return OfficialHistory(
        triangle,
        entities=entity_grid(),
        weeks=week_starts_between(config.start_date, config.end_date),
    )


def training_as_of_dates(config) -> list:
    start = config.get("time.training_as_of.start", "2021-06-07")
    step = int(config.get("time.training_as_of.step_days", 7))
    return date_range_days(start, config.data_cutoff, step=step)


def run(limit_as_of: int | None = None) -> dict[str, Any]:
    config = get_config()
    interim = config.path("data_interim")
    processed = ensure_dir(config.path("data_processed"))

    LOGGER.info("Stage 2a | feature store")
    store = build_store(interim)
    store.save(processed / "feature_store.parquet")
    write_parquet(store.availability_profile(), processed / "feature_availability.parquet")

    LOGGER.info("Stage 2b | official reporting history")
    history = build_history(interim, config)

    LOGGER.info("Stage 2c | point-in-time design matrix")
    canonical = read_parquet(interim / "canonical_events.parquet")
    assembler = FeatureAssembler(
        store, history, config=config, events_for_delay=canonical
    )

    as_of_dates = training_as_of_dates(config)
    if limit_as_of:
        as_of_dates = as_of_dates[-int(limit_as_of):]
    LOGGER.info(
        "  %s as-of dates from %s to %s", len(as_of_dates), as_of_dates[0], as_of_dates[-1]
    )

    started = time.perf_counter()
    design = assembler.assemble_many(as_of_dates)
    LOGGER.info(
        "  assembly took %.1fs (%.0f ms per as-of date)",
        time.perf_counter() - started,
        1000 * (time.perf_counter() - started) / max(len(as_of_dates), 1),
    )

    LOGGER.info("Stage 2d | targets")
    labels = build_early_warning_labels(history, as_of_dates, config=config)
    targets = build_forecast_targets(
        history, as_of_dates, config.forecast_days, config=config
    )

    write_parquet(design, processed / "design_matrix.parquet")
    write_parquet(labels, processed / "early_warning_labels.parquet")
    write_parquet(targets, processed / "forecast_targets.parquet")

    # A tidy observed-vs-final series for the app and the evaluation suite.
    final = history.final_counts()
    observed_final = pd.DataFrame(
        {
            "entity_key": [key for key in history.entities for _ in history.weeks],
            "week_start": [week for _ in history.entities for week in history.weeks],
            "reported_final": final.reshape(-1),
        }
    )
    write_parquet(observed_final, processed / "observed_final_series.parquet")

    manifest = {
        "stage": "build_features",
        "n_store_rows": int(len(store)),
        "n_features": len(store.features),
        "n_entities": len(history.entities),
        "n_weeks": history.n_weeks,
        "n_as_of_dates": len(as_of_dates),
        "as_of_first": str(as_of_dates[0]),
        "as_of_last": str(as_of_dates[-1]),
        "design_matrix_rows": int(len(design)),
        "label_positive_rate": float(
            labels.loc[labels["label_observable"], "label"].mean()
        ) if len(labels) else None,
    }
    write_json(manifest, processed / "features_manifest.json")
    LOGGER.info("Stage 2 complete | %s", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-as-of", type=int, default=None,
                        help="use only the most recent N as-of dates (development shortcut)")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    setup_logging(args.log_level)
    run(limit_as_of=args.limit_as_of)


if __name__ == "__main__":
    main()
