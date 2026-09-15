"""BEACON adapter - screened epidemic intelligence signals.

BEACON sits one level above raw media: signals have been triaged and carry a
verification state. The adapter keeps verified and unverified streams apart
rather than summing them, because they have very different false-positive
rates and the fusion model should be allowed to weight them differently.

BEACON also records what each signal was built from (``underlying_sources``).
Signals derived purely from media are flagged, because they are *not*
independent corroboration of a media signal already in the system -- this feeds
the evidence-independence discount in :mod:`src.linkage.independence`.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["BEACONAdapter"]


class BEACONAdapter(SourceAdapter):
    """Triaged intelligence signals with verification state."""

    source_name = "BEACON"
    source_type = SourceType.AGGREGATOR
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.AGGREGATOR
    reliability = 0.62
    sample_filename = "beacon_signals_sample.csv"
    ingestion_lag_days = 1
    licence = "Restricted - partner access"
    homepage = "https://www.efsa.europa.eu"
    live_env_var = "BEACON_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No BEACON rows matched the configured panel.")
            return output

        frame["signal_strength"] = pd.to_numeric(frame["signal_strength"], errors="coerce").fillna(0.0)
        frame["is_verified"] = frame["verification_status"].astype(str).str.lower().eq("verified")
        frame["verified_strength"] = frame["signal_strength"] * frame["is_verified"].astype(float)
        frame["media_only"] = frame["underlying_sources"].astype(str).str.strip().eq("media")

        weekly = to_weekly(
            frame,
            # A signal is usable once screened, not when first detected.
            date_col="screened_date",
            group_cols=["iso3", "disease_code"],
            agg={
                "signal_id": "count",
                "is_verified": "sum",
                "signal_strength": "max",
                "verified_strength": "sum",
                "media_only": "mean",
            },
        ).rename(columns={"signal_id": "n_signals", "is_verified": "n_verified"})

        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="n_signals",
            prefix="beacon",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )
        weekly["beacon_verified_signals"] = weekly["n_verified"].astype(float)
        weekly["beacon_max_strength"] = weekly["signal_strength"]
        weekly["beacon_verified_strength"] = weekly["verified_strength"]
        # Share of signals that rest on media alone -> dependence flag, not a risk score
        weekly["beacon_media_dependence"] = weekly["media_only"].clip(0.0, 1.0)

        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("beacon_abnormal_volume", "z-score"),
                ("beacon_acceleration", "dlog2"),
                ("beacon_verified_signals", "count"),
                ("beacon_max_strength", "score"),
                ("beacon_verified_strength", "score-sum"),
                ("beacon_media_dependence", "share"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_signals",
            query_template="beacon:signals?country={iso3}&disease={disease}",
            note="Screened epidemic intelligence; verification state preserved separately.",
        )
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "beacon_media_dependence records the share of signals resting on media alone; "
            "it is used to discount evidence independence, never as a risk feature."
        )
        return output
