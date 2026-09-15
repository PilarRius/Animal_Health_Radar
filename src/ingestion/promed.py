"""ProMED-mail adapter (optional source).

ProMED posts are sparse but human-curated, so they behave very differently from
bulk media: low volume, high specificity, and a curator comment that often
carries the epidemiological interpretation. The adapter emits a post count and
a confirmation-weighted intensity rather than an anomaly z-score, because the
series is too sparse for a control chart to be meaningful.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import emit_weekly_signals, to_weekly
from src.schemas.enums import EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["ProMEDAdapter"]

_CONFIDENCE_WEIGHT: dict[str, float] = {
    "confirmed": 1.0,
    "suspected": 0.55,
    "unverified": 0.25,
}


class ProMEDAdapter(SourceAdapter):
    """Curated outbreak reports from ProMED-mail."""

    source_name = "ProMED"
    source_type = SourceType.MEDIA
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.MEDIA
    reliability = 0.66
    sample_filename = "promed_posts_sample.csv"
    ingestion_lag_days = 1
    licence = "ISID ProMED terms of use"
    homepage = "https://promedmail.org"
    live_env_var = "PROMED_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        if frame.empty:
            output.notes.append("ProMED sample is empty for this panel.")
            return output
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No ProMED rows matched the configured panel.")
            return output

        frame["confidence_weight"] = (
            frame["confidence"].astype(str).str.lower().map(_CONFIDENCE_WEIGHT).fillna(0.25)
        )
        frame["curated"] = frame["curator_comment_present"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        ).astype(float)

        weekly = to_weekly(
            frame,
            date_col="published_date",
            group_cols=["iso3", "disease_code"],
            agg={"post_id": "count", "confidence_weight": "sum", "curated": "mean"},
        ).rename(columns={"post_id": "n_posts"})

        weekly["promed_post_count"] = weekly["n_posts"].astype(float)
        weekly["promed_confidence_weighted"] = weekly["confidence_weight"]
        weekly["promed_curated_share"] = weekly["curated"]

        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("promed_post_count", "count"),
                ("promed_confidence_weighted", "weighted count"),
                ("promed_curated_share", "share"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_posts",
            query_template="promed:search?country={iso3}&disease={disease}",
            note="Curated but unverified; sparse series, no control chart applied.",
        )
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "Series is deliberately left un-standardised: with a median of zero posts per "
            "country-week an EWMA z-score would be dominated by its own floor."
        )
        return output
