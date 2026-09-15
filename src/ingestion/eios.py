"""EIOS adapter - clean interface, clearly-labelled MOCK data.

The WHO Epidemic Intelligence from Open Sources platform is access-restricted;
this repository has no credentials and does not pretend otherwise. What the
adapter provides is:

* a **real interface** -- identical contract to every other adapter, so
  plugging in genuine EIOS extracts is a matter of implementing
  :meth:`fetch_live` and nothing else;
* a **mock corpus** whose every record is stamped ``realism = mock`` and
  propagated as such into the provenance ledger and the dashboard, so no one
  can mistake it for an observation.

The reliability weight is deliberately modest and the app displays a MOCK badge
wherever EIOS contributes to a score.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import DataRealism, EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["EIOSAdapter"]


class EIOSAdapter(SourceAdapter):
    """Board-item clustering signals from EIOS (mock corpus in this build)."""

    source_name = "EIOS"
    source_type = SourceType.AGGREGATOR
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.AGGREGATOR
    reliability = 0.50
    sample_filename = "eios_board_items_mock.csv"
    sample_realism = DataRealism.MOCK
    ingestion_lag_days = 1
    licence = "Restricted - WHO EIOS partner access required"
    homepage = "https://www.who.int/initiatives/eios"
    live_env_var = "EIOS_CLIENT_ID"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)
        output.notes.append(
            "EIOS records in this build are MOCK. They exercise the interface and are "
            "labelled realism='mock' everywhere they surface, including the dashboard."
        )

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No EIOS mock rows matched the configured panel.")
            return output

        frame["relevance"] = pd.to_numeric(frame["relevance"], errors="coerce").fillna(0.0)
        frame["n_articles_in_cluster"] = pd.to_numeric(
            frame["n_articles_in_cluster"], errors="coerce"
        ).fillna(0.0)
        frame["not_dismissed"] = ~frame["triage_state"].astype(str).str.lower().eq("dismissed")
        frame["effective_cluster"] = frame["n_articles_in_cluster"] * frame["not_dismissed"].astype(float)

        weekly = to_weekly(
            frame,
            date_col="first_seen_date",
            group_cols=["iso3", "disease_code"],
            agg={
                "item_id": "count",
                "effective_cluster": "sum",
                "relevance": "mean",
                "not_dismissed": "sum",
            },
        ).rename(columns={"item_id": "n_items", "not_dismissed": "n_retained"})

        weekly = derive_anomaly_block(
            weekly,
            group_cols=["iso3", "disease_code"],
            value_col="effective_cluster",
            prefix="eios",
            alpha=float(self.config.get("features.ewma_alpha", 0.30)),
        )
        weekly["eios_retained_items"] = weekly["n_retained"].astype(float)
        weekly["eios_mean_relevance"] = weekly["relevance"]

        signals, provenance = emit_weekly_signals(
            self,
            weekly,
            signal_columns=[
                ("eios_abnormal_volume", "z-score"),
                ("eios_retained_items", "count"),
                ("eios_mean_relevance", "score"),
            ],
            family=SignalFamily.INTELLIGENCE,
            denominator_col="n_items",
            query_template="eios:boards/AnimalHealth?country={iso3}&disease={disease}",
            note="MOCK DATA - interface demonstration only, not a WHO EIOS extract.",
        )
        output.signals.extend(signals)
        output.provenance.extend(provenance)
        return output
