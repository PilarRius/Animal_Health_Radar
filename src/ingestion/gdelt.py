"""GDELT adapter - media volume turned into epidemiologically usable anomalies.

GDELT publishes counts of news articles. A count is not evidence of disease:
it is evidence of *attention*, which is driven by real events, by news cycles,
by language coverage and by echo of official announcements.

This adapter therefore never emits an article count as a risk score. It emits
four derived quantities per country-disease-week:

``gdelt_abnormal_volume``
    EWMA control-chart z-score of log article volume: how unusual is the
    current level of attention for this series?
``gdelt_source_diversity``
    Distinct outlets per article, blended with language count. A story carried
    by twenty independent outlets is worth more than twenty syndications of one
    wire item.
``gdelt_acceleration``
    Second difference of log volume: is attention accelerating?
``gdelt_tone_negativity``
    Mean article tone flipped in sign, a weak proxy for severity framing.

Availability is stamped one day after the end of the reference week, matching
GDELT's near-real-time publication.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import derive_anomaly_block, to_weekly
from src.schemas.canonical import SignalRecord
from src.schemas.enums import EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["GDELTAdapter"]


class GDELTAdapter(SourceAdapter):
    """Derived media-attention anomalies from GDELT article volumes."""

    source_name = "GDELT"
    source_type = SourceType.MEDIA
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.MEDIA
    reliability = 0.45
    sample_filename = "gdelt_daily_sample.csv"
    ingestion_lag_days = 1
    licence = "GDELT Project - open, attribution required"
    homepage = "https://www.gdeltproject.org"
    live_env_var = "GDELT_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        diseases = load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.loc[
            raw["iso3"].astype(str).str.upper().isin(countries)
            & raw["disease_code"].astype(str).str.upper().isin(diseases)
        ].copy()
        if frame.empty:
            output.notes.append("No GDELT rows matched the configured panel.")
            return output

        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()

        weekly = to_weekly(
            frame,
            date_col="date",
            group_cols=["iso3", "disease_code"],
            agg={
                "n_articles": "sum",
                "n_distinct_sources": "sum",
                "n_languages": "max",
                "avg_tone": "mean",
            },
        )
        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="n_articles",
            prefix="gdelt",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )

        # Source diversity: outlets per article, lifted by multi-language coverage.
        weekly["gdelt_source_diversity"] = (
            (weekly["n_distinct_sources"] / weekly["n_articles"].clip(lower=1.0)).clip(0.0, 1.0)
            * (1.0 + 0.18 * (weekly["n_languages"].fillna(1.0) - 1.0))
        ).clip(0.0, 2.0)
        weekly["gdelt_tone_negativity"] = (-weekly["avg_tone"].fillna(0.0) / 10.0).clip(-1.0, 2.0)

        emitted = [
            ("gdelt_abnormal_volume", "z-score", SignalFamily.INTELLIGENCE),
            ("gdelt_acceleration", "dlog2", SignalFamily.INTELLIGENCE),
            ("gdelt_source_diversity", "ratio", SignalFamily.INTELLIGENCE),
            ("gdelt_baseline_ratio", "ratio", SignalFamily.INTELLIGENCE),
            ("gdelt_tone_negativity", "index", SignalFamily.INTELLIGENCE),
        ]

        for row in weekly.to_dict(orient="records"):
            week_start = pd.Timestamp(row["week_start"]).date()
            # Week is complete at week_start + 6 days; GDELT is available the next day.
            available = week_start + pd.Timedelta(days=6 + self.ingestion_lag_days)
            available_date = available.date() if hasattr(available, "date") else available
            if available_date > self.cutoff:
                continue

            provenance = self.make_provenance(
                record_id=f"GDELT-{row['iso3']}-{row['disease_code']}-{week_start}",
                published_at=week_start + pd.Timedelta(days=6),
                available_from=available_date,
                query=f"gdelt:doc:theme=ANIMAL_DISEASE_{row['disease_code']}&country={row['iso3']}",
                notes="Derived anomaly statistics; raw article counts are never used as risk.",
            )

            for signal_name, unit, family in emitted:
                value = row.get(signal_name)
                if value is None or pd.isna(value):
                    continue
                output.signals.append(
                    SignalRecord(
                        signal_id=f"{signal_name}:{row['iso3']}:{row['disease_code']}:{week_start}",
                        country_iso3=row["iso3"],
                        disease=row["disease_code"],
                        reference_date=week_start,
                        available_from=available_date,
                        signal_name=signal_name,
                        signal_family=family,
                        value=float(value),
                        unit=unit,
                        denominator=float(row["n_articles"]),
                        provenance=provenance,
                    )
                )
            output.provenance.append(provenance)

        output.notes.append(
            "GDELT contributes abnormal volume, acceleration, source diversity and tone. "
            "Raw counts are exposed only as the denominator for audit."
        )
        return output
