"""Fetch real PADI-web articles from the public JSON API and cache them.

::

    python scripts/fetch_padiweb.py
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

from src.ingestion.padiweb_client import (
    PADIWEB_SOURCE_CATEGORIES,
    articles_to_frame,
    fetch_padiweb_articles,
)
from src.utils.config import clear_config_cache, get_config, load_countries
from src.utils.io import write_csv
from src.utils.logging_utils import get_logger, setup_logging
from src.utils.paths import ensure_dir

LOGGER = get_logger("scripts.fetch_padiweb")


def main() -> None:
    setup_logging()
    clear_config_cache()
    config = get_config()
    out_dir = ensure_dir(config.path("data_raw") / "padiweb")
    out = out_dir / "padiweb_articles_panel.csv"

    published_after = str(
        config.get("sources.padiweb.published_after", config.get("time.start_date", "2021-01-01"))
    )
    published_before = str(config.get("sources.padiweb.published_before", "") or "") or None
    countries = list(load_countries().keys())

    articles = fetch_padiweb_articles(
        disease_categories=PADIWEB_SOURCE_CATEGORIES,
        iso3_countries=countries,
        published_after=published_after,
        published_before=published_before,
    )
    frame = articles_to_frame(articles)
    write_csv(frame, out)
    LOGGER.info("Wrote %s rows -> %s", len(frame), out)
    if not frame.empty:
        print(frame.groupby(["disease_code", "iso3"]).size().sort_values(ascending=False).head(30))


if __name__ == "__main__":
    main()
