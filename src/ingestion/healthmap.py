"""HealthMap adapter (optional source).

HealthMap aggregates many of the same feeds as GDELT and ProMED, so its main
contribution here is **geolocation granularity** rather than independent
evidence. Two consequences are built into the adapter:

* rows flagged as duplicates of an existing feed item are counted separately
  and excluded from the headline alert count;
* the source lives in the ``media`` evidence cluster, so the independence
  calculation already discounts it against GDELT and PADI-web.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["HealthMapAdapter"]


class HealthMapAdapter(SourceAdapter):
    """Geo-coded disease alerts aggregated from open feeds."""

    source_name = "HealthMap"
    source_type = SourceType.MEDIA
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.MEDIA
    reliability = 0.44
    sample_filename = "healthmap_alerts_sample.csv"
    ingestion_lag_days = 1
    licence = "HealthMap / Boston Children's Hospital terms of use"
    homepage = "https://healthmap.org"
    live_env_var = "HEALTHMAP_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        if frame.empty:
            output.notes.append("HealthMap sample is empty for this panel.")
            return output
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No HealthMap rows matched the configured panel.")
            return output

        frame["is_duplicate"] = frame["duplicate_of_feed_item"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
        frame["unique_alert"] = (~frame["is_duplicate"]).astype(float)
        frame["official_feed"] = frame["feed"].astype(str).str.lower().eq("official").astype(float)

        weekly = to_weekly(
            frame,
            date_col="published_date",
            group_cols=["iso3", "disease_code"],
            agg={
                "alert_id": "count",
                "unique_alert": "sum",
                "is_duplicate": "mean",
                "official_feed": "mean",
            },
        ).rename(columns={"alert_id": "n_alerts"})

        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="unique_alert",
            prefix="healthmap",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )
        weekly["healthmap_unique_alerts"] = weekly["unique_alert"]
        weekly["healthmap_duplicate_share"] = weekly["is_duplicate"]
        weekly["healthmap_official_feed_share"] = weekly["official_feed"]

        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("healthmap_abnormal_volume", "z-score"),
                ("healthmap_unique_alerts", "count"),
                ("healthmap_duplicate_share", "share"),
                ("healthmap_official_feed_share", "share"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_alerts",
            query_template="healthmap:alerts?country={iso3}&disease={disease}",
            note="Feed aggregation with explicit duplicate accounting.",
        )
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "healthmap_duplicate_share and healthmap_official_feed_share quantify how much of "
            "this source echoes material already counted elsewhere."
        )
        return output
