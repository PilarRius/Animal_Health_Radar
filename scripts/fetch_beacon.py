"""Fetch real BEACON reports from the public API and cache them.

::

    python scripts/fetch_beacon.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

from src.ingestion.beacon_client import (
    BEACON_DISEASE_IDS,
    fetch_beacon_reports,
    reports_to_signal_frame,
)
from src.utils.config import clear_config_cache, get_config
from src.utils.io import write_csv
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.fetch_beacon")


def main() -> None:
    setup_logging()
    clear_config_cache()
    config = get_config()
    out_dir = ensure_dir(config.path("data_raw") / "beacon")
    out = out_dir / "beacon_reports_panel.csv"

    reports = fetch_beacon_reports(disease_ids=list(BEACON_DISEASE_IDS.values()))
    frame = reports_to_signal_frame(reports)
    write_csv(frame, out)
    LOGGER.info("Wrote %s rows -> %s", len(frame), out)
    if not frame.empty:
        print(frame.groupby(["disease_code", "iso3"]).size().sort_values(ascending=False).head(20))


if __name__ == "__main__":
    main()
