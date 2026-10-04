"""PADI-web adapter — CIRAD news-based animal disease intelligence.

In ``pilot`` / ``offline`` / ``live`` modes the adapter calls the public
PADI-web JSON listing at ``https://padi-web.cirad.fr/en/articles/api/``
(no API key for the free limited tier). Results are cached under
``data/raw/padiweb/`` so subsequent runs stay reproducible offline.

Sample mode still uses the labelled synthetic corpus.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.padiweb_client import (
    PADIWEB_API_BASE,
    PADIWEB_SOURCE_CATEGORIES,
    articles_to_frame,
    fetch_padiweb_articles,
)
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import DataRealism, EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.io import read_csv, write_csv
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["PADIWebAdapter"]


class PADIWebAdapter(SourceAdapter):
    """Relevance-weighted news event signals from PADI-web."""

    source_name = "PADI-web"
    source_type = SourceType.MEDIA
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.MEDIA
    reliability = 0.58
    sample_filename = "padiweb_articles_sample.csv"
    ingestion_lag_days = 1
    licence = "CIRAD PADI-web terms of use — free limited research/web monitoring tier"
    homepage = "https://padi-web.cirad.fr"
    live_env_var = "PADIWEB_API_BASE"  # optional override; public listing needs no key

    def load_raw(self) -> pd.DataFrame:
        mode = self.config.data_mode
        if mode in {"pilot", "offline", "live"}:
            cache = self._cache_path()
            refresh = str(self.config.get("sources.padiweb.refresh", "false")).lower() in {
                "1",
                "true",
                "yes",
            }
            if cache.is_file() and not refresh:
                LOGGER.info("%s: loading cached extract %s", self.source_name, cache.name)
                return read_csv(cache)
            try:
                frame = self.fetch_live()
            except Exception as exc:  # noqa: BLE001
                if cache.is_file():
                    LOGGER.warning(
                        "%s: live fetch failed (%s); falling back to cache %s",
                        self.source_name,
                        exc,
                        cache.name,
                    )
                    return read_csv(cache)
                raise LiveSourceUnavailable(
                    f"{self.source_name}: live fetch failed and no cache at {cache}: {exc}"
                ) from exc
            cache.parent.mkdir(parents=True, exist_ok=True)
            write_csv(frame, cache)
            LOGGER.info("%s: wrote cache %s (%s rows)", self.source_name, cache, len(frame))
            return frame
        return super().load_raw()

    def fetch_live(self) -> pd.DataFrame:
        import os

        api_base = (
            os.environ.get(self.live_env_var or "", "")
            or str(self.config.get("sources.padiweb.api_base", PADIWEB_API_BASE))
            or PADIWEB_API_BASE
        )
        published_after = str(
            self.config.get("sources.padiweb.published_after", self.config.get("time.start_date", "2021-01-01"))
        )
        published_before = str(self.config.get("sources.padiweb.published_before", "") or "") or None
        countries = list(load_countries().keys())
        LOGGER.info(
            "%s: fetching public articles API %s/en/articles/api/ (no key)",
            self.source_name,
            api_base.rstrip("/"),
        )
        articles = fetch_padiweb_articles(
            disease_categories=PADIWEB_SOURCE_CATEGORIES,
            iso3_countries=countries,
            published_after=published_after,
            published_before=published_before,
            api_base=api_base,
        )
        return articles_to_frame(articles)

    def _cache_path(self) -> Path:
        raw = self.config.path("data_raw")
        return raw / "padiweb" / "padiweb_articles_panel.csv"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        if frame.empty:
            output.notes.append("No PADI-web rows loaded.")
            return output

        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No PADI-web rows matched the configured panel.")
            return output

        realism = (
            DataRealism.REAL
            if self.config.data_mode in {"pilot", "offline", "live"}
            else None
        )
        if "data_realism" in frame.columns and frame["data_realism"].astype(str).str.lower().eq("real").any():
            realism = DataRealism.REAL

        frame["is_event"] = frame["is_epidemiological_event"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
        frame["relevance_score"] = pd.to_numeric(frame["relevance_score"], errors="coerce").fillna(0.0)
        frame["weighted_event"] = frame["relevance_score"] * frame["is_event"].astype(float)

        weekly = to_weekly(
            frame,
            # PADI-web makes the extraction, not the article, available
            date_col="extracted_date",
            group_cols=["iso3", "disease_code"],
            agg={
                "article_id": "count",
                "weighted_event": "sum",
                "relevance_score": "mean",
                "is_event": "sum",
                "language": "nunique",
            },
        ).rename(columns={"article_id": "n_articles", "is_event": "n_events"})

        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="weighted_event",
            prefix="padiweb",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )
        weekly["padiweb_event_rate"] = weekly["weighted_event"]
        weekly["padiweb_mean_relevance"] = weekly["relevance_score"]
        weekly["padiweb_language_spread"] = weekly["language"].astype(float)

        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("padiweb_abnormal_volume", "z-score"),
                ("padiweb_acceleration", "dlog2"),
                ("padiweb_event_rate", "relevance-weighted count"),
                ("padiweb_mean_relevance", "score"),
                ("padiweb_language_spread", "count"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_articles",
            query_template="padiweb:articles/api?country={iso3}&disease={disease}",
            note=(
                "Real PADI-web public articles API."
                if realism == DataRealism.REAL
                else "Relevance-weighted extraction counts; unverified media intelligence."
            ),
        )
        if realism == DataRealism.REAL:
            for prov in provenance:
                prov.realism = DataRealism.REAL

        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "PADI-web public articles API (padi-web.cirad.fr/en/articles/api/). "
            "Relevance-weighted extraction counts; media-cluster intelligence — "
            "not independent of GDELT/ProMED/HealthMap on the same stories. "
            "Reference date is the PADI-web extraction/scraping date."
        )
        return output
