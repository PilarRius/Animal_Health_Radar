"""WAHIS Six-Month Report (SMR) adapter — semester status, not outbreaks.

SMR answers: what is the official semester disease status for a country?
It must never be mixed into the INFUR outbreak burden series. We emit
country×disease×semester *covariates* that capture reporting/status intensity
(useful where endemic countries under-report HPAI in INFUR).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.wahis_mapping import map_country_iso3, map_disease_code
from src.schemas.canonical import CovariateRecord
from src.schemas.enums import DataRealism, EvidenceCluster, SourceTier, SourceType
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["SMRAdapter"]

_OCCURRENCE_PRESENT = {
    "present",
    "disease present",
    "confirmed infection",
    "infection",
    "suspected",
}


def _semester_end(year: int, period_code: str) -> date:
    code = (period_code or "").upper()
    if code in {"SEM02", "S2", "SECOND"}:
        return date(int(year), 12, 31)
    return date(int(year), 6, 30)


class SMRAdapter(SourceAdapter):
    """Offline SMR disease-status covariates from local CSV/Excel extracts."""

    source_name = "WAHIS_SMR"
    source_type = SourceType.OFFICIAL
    source_tier = SourceTier.SECONDARY_OFFICIAL
    evidence_cluster = EvidenceCluster.OFFICIAL
    reliability = 0.85
    downstream_of_official = False
    sample_filename = ""  # no synthetic SMR; optional in sample mode
    ingestion_lag_days = 0
    licence = "WOAH WAHIS public terms — attribution required; no commercial site redistribution; no endorsement"
    homepage = "https://wahis.woah.org"
    live_env_var = None  # never call WAHIS API

    def load_raw(self) -> pd.DataFrame:
        if self.config.data_mode == "sample":
            LOGGER.info("%s: sample mode — no SMR covariates (INFUR sample only).", self.source_name)
            return pd.DataFrame()
        path = self._resolve_offline_path()
        if path is None:
            raise LiveSourceUnavailable(
                f"{self.source_name}: no offline SMR file under data/raw/smr/ or data/raw/smr_*.csv"
            )
        LOGGER.info("%s: loading offline file %s (no API)", self.source_name, path.name)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            frame = pd.read_excel(path)
            return self._filter_panel(frame)
        # Chunked CSV read — full SMR export is ~270 MB.
        usecols = [
            "reportId",
            "reportInfoId",
            "country",
            "isoCodeCountry",
            "year",
            "period",
            "periodCode",
            "status",
            "reportDate",
            "diseaseCategory",
            "diseaseId",
            "diseaseName",
            "wildOccurrenceCode",
            "wildOccurrenceLabel",
            "domesticOccurrenceCode",
            "domesticOccurrenceLabel",
            "newOutbreak",
            "totalOutbreak",
        ]
        chunks: list[pd.DataFrame] = []
        for chunk in pd.read_csv(path, usecols=lambda c: c in usecols, chunksize=200_000, low_memory=False):
            filtered = self._filter_panel(chunk)
            if not filtered.empty:
                chunks.append(filtered)
        if not chunks:
            return pd.DataFrame()
        frame = pd.concat(chunks, ignore_index=True)
        # One status row per country×disease×semester (drop quantity duplicates).
        keys = [c for c in ("isoCodeCountry", "country", "diseaseName", "year", "periodCode") if c in frame.columns]
        if keys:
            frame = frame.drop_duplicates(subset=keys, keep="first")
        LOGGER.info("%s: kept %s semester status rows after panel filter", self.source_name, len(frame))
        return frame

    @staticmethod
    def _filter_panel(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "diseaseName" not in frame.columns:
            return frame.iloc[0:0].copy()
        disease = frame["diseaseName"].astype(str)
        mask = disease.str.contains(
            r"high pathogenicity|Influenza A|African swine fever",
            case=False,
            na=False,
        )
        return frame.loc[mask].copy()

    def _resolve_offline_path(self) -> Path | None:
        raw = self.config.path("data_raw")
        candidates: list[Path] = []
        smr_dir = raw / "smr"
        if smr_dir.is_dir():
            candidates.extend(sorted(smr_dir.glob("*.csv")))
            candidates.extend(sorted(smr_dir.glob("*.xlsx")))
        candidates.extend(sorted(raw.glob("smr*.csv")))
        candidates.extend(sorted(raw.glob("smr*.xlsx")))
        return candidates[0] if candidates else None

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        output = AdapterOutput(source_name=self.source_name)
        if raw.empty:
            output.notes.append("No SMR rows loaded.")
            return output

        kept = 0
        skipped = 0
        for row in raw.to_dict(orient="records"):
            disease = map_disease_code(row.get("diseaseName") or row.get("disease"))
            iso3 = map_country_iso3(row.get("country"), row.get("isoCodeCountry"))
            if disease is None or iso3 is None:
                skipped += 1
                continue
            try:
                year = int(row.get("year"))
            except (TypeError, ValueError):
                skipped += 1
                continue
            period = str(row.get("periodCode") or row.get("period") or "SEM01")
            ref = _semester_end(year, period)
            published = self._as_date(row.get("reportDate")) or ref
            # Knowable only once the report exists; never before the semester reference.
            available = max(published, ref)
            if not self._within_cutoff(available):
                skipped += 1
                continue

            domestic = str(row.get("domesticOccurrenceLabel") or row.get("domesticOccurrenceCode") or "")
            wild = str(row.get("wildOccurrenceLabel") or row.get("wildOccurrenceCode") or "")
            present = int(
                any(token in domestic.lower() for token in _OCCURRENCE_PRESENT)
                or any(token in wild.lower() for token in _OCCURRENCE_PRESENT)
                or str(row.get("diseaseCategory") or "").upper() == "PRESENT"
            )
            new_ob = self._opt_float(row.get("newOutbreak")) or 0.0
            total_ob = self._opt_float(row.get("totalOutbreak")) or 0.0

            record_id = f"SMR-{iso3}-{disease}-{year}-{period}"
            provenance = self.make_provenance(
                record_id=record_id,
                published_at=available,
                url=self.homepage,
                query=f"wahis:smr:{row.get('reportId')}",
                realism=DataRealism.REAL,
                notes="Semester status covariate — not an outbreak event.",
            )
            for name, value, unit in (
                ("smr_disease_present", float(present), "flag"),
                ("smr_new_outbreaks", float(new_ob), "count"),
                ("smr_total_outbreaks", float(total_ob), "count"),
            ):
                output.covariates.append(
                    CovariateRecord(
                        covariate_id=f"{name}:{iso3}:{disease}:{year}:{period}",
                        country_iso3=iso3,
                        disease=disease,
                        reference_date=ref,
                        available_from=available,
                        variable=name,
                        value=value,
                        unit=unit,
                        aggregation="semester_status",
                        provenance=provenance,
                    )
                )
            output.provenance.append(provenance)
            kept += 1

        output.notes.append(
            f"SMR covariates from offline extract: {kept} status rows kept, {skipped} skipped. "
            "IDs are independent of INFUR. Never treat these as outbreak events."
        )
        return output

    def _as_date(self, value: Any) -> date | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        ts = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(ts):
            return None
        return ts.date()

    def _within_cutoff(self, value: date | None) -> bool:
        return value is not None and value <= self.cutoff

    @staticmethod
    def _opt_float(value: Any) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
