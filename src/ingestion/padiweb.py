"""PADI-web adapter - news-based animal disease intelligence (CIRAD).

PADI-web differs from raw GDELT in that its pipeline already performs event
extraction: each article carries a relevance score and a flag for whether an
epidemiological event was detected. The adapter exploits that by emitting a
*relevance-weighted* event rate alongside the volume anomaly, so a handful of
high-confidence extractions is not drowned out by a flood of passing mentions.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["PADIWebAdapter"]


class PADIWebAdapter(SourceAdapter):
    """Relevance-weighted news event signals."""

    source_name = "PADI-web"
    source_type = SourceType.MEDIA
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.MEDIA
    reliability = 0.58
    sample_filename = "padiweb_articles_sample.csv"
    ingestion_lag_days = 1
    licence = "CIRAD PADI-web terms of use"
    homepage = "https://padi-web.cirad.fr"
    live_env_var = "PADIWEB_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No PADI-web rows matched the configured panel.")
            return output

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
            query_template="padiweb:events?country={iso3}&disease={disease}",
            note="Relevance-weighted extraction counts; unverified media intelligence.",
        )
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "Reference date is the PADI-web extraction date, which can lag article "
            "publication by a day; availability is stamped from the extraction date."
        )
        return output
