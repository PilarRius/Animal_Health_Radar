"""BEACON adapter — curated epidemic intelligence from the public API.

In ``pilot`` / ``offline`` / ``live`` modes the adapter calls
``https://api.beaconbio.org/public/report`` (no API key). Results are cached
under ``data/raw/beacon/`` so subsequent runs stay reproducible offline.

Sample mode still uses the labelled synthetic corpus.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.beacon_client import (
    BEACON_API_BASE,
    BEACON_DISEASE_IDS,
    fetch_beacon_reports,
    reports_to_signal_frame,
)
from src.ingestion.signal_derivation import derive_anomaly_block, emit_weekly_signals, to_weekly
from src.schemas.enums import DataRealism, EvidenceCluster, SignalFamily, SourceTier, SourceType
from src.utils.config import load_countries, load_diseases
from src.utils.io import read_csv, write_csv
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["BEACONAdapter"]


class BEACONAdapter(SourceAdapter):
    """Triaged intelligence signals with verification state."""

    source_name = "BEACON"
    source_type = SourceType.AGGREGATOR
    source_tier = SourceTier.INTELLIGENCE
    evidence_cluster = EvidenceCluster.AGGREGATOR
    reliability = 0.70
    sample_filename = "beacon_signals_sample.csv"
    ingestion_lag_days = 1
    licence = "Public website content — attribute BEACON / beaconbio.org"
    homepage = "https://beaconbio.org"
    live_env_var = "BEACON_API_BASE"  # optional override; public API needs no key

    def load_raw(self) -> pd.DataFrame:
        mode = self.config.data_mode
        if mode in {"pilot", "offline", "live"}:
            cache = self._cache_path()
            refresh = str(self.config.get("sources.beacon.refresh", "true")).lower() in {
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
        api_base = (
            __import__("os").environ.get(self.live_env_var or "", "")
            or str(self.config.get("sources.beacon.api_base", BEACON_API_BASE))
            or BEACON_API_BASE
        )
        LOGGER.info("%s: fetching public API %s/public/report (no key)", self.source_name, api_base)
        disease_ids = list(BEACON_DISEASE_IDS.values())
        reports = fetch_beacon_reports(disease_ids=disease_ids, api_base=api_base)
        return reports_to_signal_frame(reports)

    def _cache_path(self) -> Path:
        raw = self.config.path("data_raw")
        return raw / "beacon" / "beacon_reports_panel.csv"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries, diseases = load_countries(), load_diseases()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        if frame.empty:
            output.notes.append("No BEACON rows loaded.")
            return output

        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame["disease_code"] = frame["disease_code"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries) & frame["disease_code"].isin(diseases)]
        if frame.empty:
            output.notes.append("No BEACON rows matched the configured panel.")
            return output

        realism = (
            DataRealism.REAL
            if self.config.data_mode in {"pilot", "offline", "live"}
            else None
        )
        if "data_realism" in frame.columns and frame["data_realism"].astype(str).str.lower().eq("real").any():
            realism = DataRealism.REAL

        frame["signal_strength"] = pd.to_numeric(frame["signal_strength"], errors="coerce").fillna(0.0)
        frame["is_verified"] = frame["verification_status"].astype(str).str.lower().eq("verified")
        frame["verified_strength"] = frame["signal_strength"] * frame["is_verified"].astype(float)
        frame["media_only"] = frame["underlying_sources"].astype(str).str.strip().eq("media")

        weekly = to_weekly(
            frame,
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
            query_template="beacon:public/report?country={iso3}&disease={disease}",
            note=(
                "Real BEACON public API reports."
                if realism == DataRealism.REAL
                else "Screened epidemic intelligence; verification state preserved separately."
            ),
        )
        # Stamp realism on provenance when live/pilot
        if realism == DataRealism.REAL:
            for prov in provenance:
                prov.realism = DataRealism.REAL

        output.signals.extend(signals)
        output.provenance.extend(provenance)
        output.notes.append(
            "BEACON public API (api.beaconbio.org/public/report). "
            "Curated aggregator intelligence — not independent of underlying media sources. "
            "beacon_media_dependence discounts evidence independence."
        )
        return output
