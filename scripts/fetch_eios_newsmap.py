"""Fetch recent EIOS-tagged news from the public WHO Pandemic Hub newsmap.

::

    python scripts/fetch_eios_newsmap.py

This is **not** a full EIOS community-portal export — only the public recent
feed at https://portal.who.int/pandemichub/newsmap/
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

from src.ingestion.eios_newsmap_client import (
    EIOS_NEWSMAP_CATEGORIES,
    fetch_newsmap_items,
    items_to_frame,
)
from src.utils.config import clear_config_cache, get_config
from src.utils.io import write_csv
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.fetch_eios_newsmap")


def main() -> None:
    setup_logging()
    clear_config_cache()
    config = get_config()
    out_dir = ensure_dir(config.path("data_raw") / "eios")
    out = out_dir / "eios_newsmap_panel.csv"
    rows = int(config.get("sources.eios.newsmap_rows", 100))

    articles = fetch_newsmap_items(
        disease_categories=EIOS_NEWSMAP_CATEGORIES,
        rows_per_category=rows,
    )
    frame = items_to_frame(articles)
    write_csv(frame, out)
    LOGGER.info("Wrote %s rows -> %s", len(frame), out)
    if not frame.empty:
        print(frame.groupby(["disease_code", "iso3"]).size().sort_values(ascending=False).head(30))
    else:
        print("No panel-mapped rows (articles lacked country/disease tags for the pilot panel).")


if __name__ == "__main__":
    main()
