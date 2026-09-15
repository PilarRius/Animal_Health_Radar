"""One-command reproducible pipeline.

::

    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --skip-ingest --skip-features
"""

from __future__ import annotations

import argparse
import time

import _bootstrap  # noqa: F401

from src.utils.logging_utils import get_logger, setup_logging

LOGGER = get_logger("scripts.run_pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-features", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-evaluate", action="store_true")
    parser.add_argument("--limit-as-of", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    setup_logging(args.log_level)

    started = time.perf_counter()

    if not args.skip_ingest:
        from scripts import ingest as ingest_mod

        LOGGER.info("=== INGEST ===")
        ingest_mod.run()

    if not args.skip_features:
        from scripts import build_features as features_mod

        LOGGER.info("=== FEATURES ===")
        features_mod.run(limit_as_of=args.limit_as_of)

    if not args.skip_train:
        from scripts import train as train_mod

        LOGGER.info("=== TRAIN ===")
        train_mod.run(app_as_of_only=True)

    if not args.skip_evaluate:
        try:
            from scripts import evaluate as evaluate_mod

            LOGGER.info("=== EVALUATE ===")
            evaluate_mod.run()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Evaluation skipped: %s", exc)

    LOGGER.info("Pipeline finished in %.1fs", time.perf_counter() - started)


if __name__ == "__main__":
    main()
