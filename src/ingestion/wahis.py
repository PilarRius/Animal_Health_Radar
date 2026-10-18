"""WOAH WAHIS INFUR adapter — primary official observation process.

Offline-first: in ``pilot`` / ``offline`` mode this adapter reads local INFUR
CSV/Excel extracts under ``data/raw/`` (or ``data/raw/infur/``). It never calls
the WAHIS API.

WAHIS is treated as the *reference observation*, never as the truth:

1. officially visible burden (nowcast inflates);
2. onset → publication gaps train the reporting-delay model;
3. first notifications are early-warning labels.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.base import AdapterOutput, LiveSourceUnavailable, SourceAdapter
from src.ingestion.wahis_mapping import map_country_iso3, map_disease_code
from src.schemas.canonical import CanonicalEvent
from src.schemas.enums import (
    ConfirmationStatus,
    DataRealism,
    EventStatus,
    EvidenceCluster,
    HostCategory,
    SourceTier,
    SourceType,
)
from src.utils.config import load_countries, load_diseases
from src.utils.io import read_csv
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["WAHISAdapter"]

# INFUR extracts often contain Follow-Up rows whose first *visible* submission
# in the file is months after outbreakStartDate (original IN missing). Those
# pairs are not usable as reporting-delay observations and would empty the
# recent nowcast weeks. Cap the trusted onset→submission gap; beyond that,
# model the event on the submission week while keeping true onset in extras.
_MAX_RELIABLE_DELAY_DAYS = 60

_STATUS_MAP: dict[str, EventStatus] = {
    "ongoing": EventStatus.ONGOING,
    "on-going": EventStatus.ONGOING,
    "resolved": EventStatus.RESOLVED,
    "closed": EventStatus.RESOLVED,
    "confirmed": EventStatus.CONFIRMED,
    "suspected": EventStatus.SUSPECTED,
    "denied": EventStatus.DENIED,
}

_DIAGNOSIS_MAP: dict[str, ConfirmationStatus] = {
    "laboratory_confirmed": ConfirmationStatus.LABORATORY_CONFIRMED,
    "clinical": ConfirmationStatus.CLINICALLY_SUSPECTED,
    "clinically_suspected": ConfirmationStatus.CLINICALLY_SUSPECTED,
    "suspected": ConfirmationStatus.CLINICALLY_SUSPECTED,
}


class WAHISAdapter(SourceAdapter):
    """Official Immediate Notification / Follow-Up Report (INFUR) outbreaks."""

    source_name = "WAHIS"
    source_type = SourceType.OFFICIAL
    source_tier = SourceTier.PRIMARY_OFFICIAL
    evidence_cluster = EvidenceCluster.OFFICIAL
    reliability = 0.95
    downstream_of_official = False
    sample_filename = "wahis_events_sample.csv"
    ingestion_lag_days = 0
    licence = "WOAH WAHIS public terms — attribution required; no commercial site redistribution; no endorsement"
    homepage = "https://wahis.woah.org"
    live_env_var = None  # API disabled; use offline extracts only

    def load_raw(self) -> pd.DataFrame:
        mode = self.config.data_mode
        if mode in {"pilot", "offline", "live"}:
            # "live" still uses offline files — never an API call.
            path = self._resolve_offline_path()
            if path is None:
                raise LiveSourceUnavailable(
                    f"{self.source_name}: no offline INFUR file under data/raw/infur/ "
                    "or data/raw/infur_*.csv|.xlsx. Drop the WOAH extract and retry."
                )
            LOGGER.info("%s: loading offline INFUR %s (no API)", self.source_name, path.name)
            if path.suffix.lower() in {".xlsx", ".xls"}:
                frame = pd.read_excel(path)
            else:
                frame = read_csv(path)
            return self._normalise_infur(frame)
        return super().load_raw()

    def fetch_live(self) -> pd.DataFrame:
        raise LiveSourceUnavailable(
            f"{self.source_name}: WAHIS API calls are disabled for this project. "
            "Place INFUR CSV/Excel under data/raw/infur/ and set data_mode=pilot."
        )

    def _resolve_offline_path(self) -> Path | None:
        raw = self.config.path("data_raw")
        candidates: list[Path] = []
        infur_dir = raw / "infur"
        if infur_dir.is_dir():
            candidates.extend(sorted(infur_dir.glob("*.csv")))
            candidates.extend(sorted(infur_dir.glob("*.xlsx")))
        candidates.extend(sorted(raw.glob("infur*.csv")))
        candidates.extend(sorted(raw.glob("infur*.xlsx")))
        # Prefer outbreak-level exports.
        preferred = [p for p in candidates if "outbreak" in p.name.lower()]
        return (preferred or candidates)[0] if (preferred or candidates) else None

    def _normalise_infur(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Collapse INFUR outbreak×species rows to one row per outbreak."""
        if raw.empty:
            return raw
        frame = raw.copy()
        # Keep HPAI / ASF only (cheap filter before mapping)
        disease_col = "disease" if "disease" in frame.columns else None
        if disease_col:
            mask = frame[disease_col].astype(str).str.contains(
                r"high pathogenicity|Influenza A|African swine fever",
                case=False,
                na=False,
            )
            frame = frame.loc[mask].copy()

        frame["_submission"] = pd.to_datetime(frame.get("submissionDate"), errors="coerce", utc=True)
        frame["_onset"] = pd.to_datetime(
            frame.get("outbreakStartDate", frame.get("eventStartDate")),
            errors="coerce",
            utc=True,
        )
        # Earliest public submission per outbreak is the knowability date.
        frame = frame.sort_values("_submission", kind="mergesort")
        outbreak_key = "outbreakId" if "outbreakId" in frame.columns else "eventId"
        # Aggregate quantities across species rows for the same outbreak/report.
        agg = {
            "eventId": "first",
            "reportId": "first",
            "reportType": "first",
            "reportNumber": "first",
            "reportStatus": "first",
            "submissionDate": "first",
            "eventStartDate": "first",
            "eventStatus": "first",
            "country": "first",
            "disease": "first",
            "reason": "first",
            "adminDivision": "first",
            "location": "first",
            "latitude": "first",
            "longitude": "first",
            "outbreakStartDate": "first",
            "outbreakEndDate": "first",
            "speciesName": lambda s: ";".join(sorted({str(x) for x in s.dropna()})),
            "isWild": "max",
            "susceptible": "sum",
            "cases": "sum",
            "deaths": "sum",
            "killed": "sum",
            "slaughtered": "sum",
            "adminLevel1Name": "first",
        }
        present = {k: v for k, v in agg.items() if k in frame.columns}
        present[outbreak_key] = "first"
        grouped = frame.groupby(outbreak_key, as_index=False, sort=False).agg(present)

        rows: list[dict[str, Any]] = []
        for row in grouped.to_dict(orient="records"):
            disease_code = map_disease_code(row.get("disease"))
            iso3 = map_country_iso3(row.get("country"))
            if disease_code is None or iso3 is None:
                continue
            publication = self._as_date(row.get("submissionDate"))
            true_onset = self._as_date(row.get("outbreakStartDate") or row.get("eventStartDate"))
            if publication is None:
                continue
            # Some INFUR rows have onset after submission; clamp so delay >= 0.
            if true_onset is not None and true_onset > publication:
                true_onset = publication
            delay_days = (
                (publication - true_onset).days if true_onset is not None else None
            )
            onset_reliable = (
                delay_days is not None and 0 <= delay_days <= _MAX_RELIABLE_DELAY_DAYS
            )
            # Modelling reference: trusted onset, else submission (knowability week).
            onset = true_onset if onset_reliable else publication
            is_wild = bool(row.get("isWild")) if row.get("isWild") is not None else False
            rows.append(
                {
                    "outbreak_id": str(row.get(outbreak_key) or row.get("eventId")),
                    "event_id": str(row.get("eventId")),
                    "iso3": iso3,
                    "disease_code": disease_code,
                    "disease": row.get("disease"),
                    "date_of_publication": publication.isoformat(),
                    "start_date": onset.isoformat() if onset else None,
                    "true_onset_date": true_onset.isoformat() if true_onset else None,
                    "onset_reliable": onset_reliable,
                    "date_of_notification": publication.isoformat(),
                    "date_of_confirmation": publication.isoformat(),
                    "date_of_suspicion": None,
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "admin1": row.get("adminLevel1Name") or row.get("adminDivision"),
                    "locality": row.get("location"),
                    "location_precision": "point"
                    if row.get("latitude") is not None
                    else "admin1",
                    "host_category": "wild" if is_wild else "domestic",
                    "species": row.get("speciesName") or "",
                    "outbreaks": 1,
                    "cases": row.get("cases"),
                    "deaths": row.get("deaths"),
                    "killed_and_disposed": row.get("killed"),
                    "susceptible": row.get("susceptible"),
                    "event_status": str(row.get("eventStatus") or "").lower(),
                    "diagnosis": "laboratory_confirmed",
                    "is_first_occurrence": "first" in str(row.get("reason") or "").lower(),
                    "report_type": row.get("reportType"),
                    "report_number": row.get("reportNumber"),
                    "control_measures": None,
                    "serotype": None,
                    "data_realism": "real",
                    "source_layer": "INFUR",
                    "infur_report_id": row.get("reportId"),
                }
            )
        LOGGER.info(
            "%s: normalised %s INFUR outbreaks into panel scope (from %s raw rows)",
            self.source_name,
            len(rows),
            len(raw),
        )
        return pd.DataFrame(rows)

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        diseases = load_diseases()
        known_iso = set(countries)
        known_disease = set(diseases)

        output = AdapterOutput(source_name=self.source_name)
        skipped_unknown = 0
        skipped_future = 0
        realism_default = (
            DataRealism.REAL
            if self.config.data_mode in {"pilot", "offline", "live"}
            else None
        )

        for row in raw.to_dict(orient="records"):
            iso3 = str(row.get("iso3", "")).upper()
            disease_code = str(row.get("disease_code", "")).upper()
            if iso3 not in known_iso or disease_code not in known_disease:
                skipped_unknown += 1
                continue

            publication = self._as_date(row.get("date_of_publication"))
            if not self._within_cutoff(publication):
                skipped_future += 1
                continue

            realism = realism_default
            if str(row.get("data_realism", "")).lower() == "synthetic":
                realism = DataRealism.SYNTHETIC
            elif str(row.get("data_realism", "")).lower() == "real":
                realism = DataRealism.REAL

            provenance = self.make_provenance(
                record_id=str(row.get("outbreak_id") or row.get("event_id")),
                published_at=publication,
                url=f"{self.homepage}/#/event/{row.get('event_id')}",
                query=f"wahis:infur:event:{row.get('event_id')}:outbreak:{row.get('outbreak_id')}",
                realism=realism,
                notes="INFUR outbreak observation; available_from = submissionDate.",
            )

            host_raw = str(row.get("host_category", "")).lower()
            host = {
                "wild": HostCategory.WILD,
                "domestic": HostCategory.DOMESTIC,
                "mixed": HostCategory.MIXED,
            }.get(host_raw, HostCategory.UNKNOWN)

            event = CanonicalEvent(
                event_id=str(row.get("outbreak_id") or row.get("event_id")),
                source_event_id=str(row.get("event_id")),
                disease=disease_code,
                disease_raw=str(row.get("disease")) if row.get("disease") is not None else None,
                serotype=self._opt_str(row.get("serotype")),
                species=[s for s in str(row.get("species", "")).split(";") if s],
                host_category=host,
                country_iso3=iso3,
                country_name=countries[iso3].name,
                admin1=self._opt_str(row.get("admin1")),
                locality=self._opt_str(row.get("locality")),
                latitude=self._opt_float(row.get("latitude")),
                longitude=self._opt_float(row.get("longitude")),
                location_precision=self._opt_str(row.get("location_precision")) or "point",
                onset_date=self._as_date(row.get("start_date")),
                suspicion_date=self._as_date(row.get("date_of_suspicion")),
                confirmation_date=self._as_date(row.get("date_of_confirmation")),
                notification_date=self._as_date(row.get("date_of_notification")),
                publication_date=publication,
                outbreaks=self._opt_int(row.get("outbreaks")) or 1,
                cases=self._opt_int(row.get("cases")),
                deaths=self._opt_int(row.get("deaths")),
                killed_disposed=self._opt_int(row.get("killed_and_disposed")),
                susceptible=self._opt_int(row.get("susceptible")),
                event_status=_STATUS_MAP.get(
                    str(row.get("event_status", "")).lower(), EventStatus.UNKNOWN
                ),
                confirmation_status=_DIAGNOSIS_MAP.get(
                    str(row.get("diagnosis", "")).lower(),
                    ConfirmationStatus.LABORATORY_CONFIRMED,
                ),
                is_first_occurrence=bool(row.get("is_first_occurrence", False)),
                report_type=self._opt_str(row.get("report_type")),
                report_number=self._opt_int(row.get("report_number")),
                available_from=publication,
                provenance=provenance,
                summary=self._opt_str(row.get("control_measures")),
                extras={
                    "control_measures": self._opt_str(row.get("control_measures")),
                    "source_layer": row.get("source_layer") or "INFUR",
                    "infur_report_id": row.get("infur_report_id"),
                    "true_onset_date": row.get("true_onset_date"),
                    "onset_reliable": bool(row.get("onset_reliable", True)),
                },
            )
            output.events.append(event)
            output.provenance.append(provenance)

        if skipped_unknown:
            output.notes.append(
                f"{skipped_unknown} row(s) dropped: country or disease outside the configured panel."
            )
        if skipped_future:
            output.notes.append(
                f"{skipped_future} row(s) dropped: publication date after the corpus cut-off "
                f"({self.cutoff})."
            )
        output.notes.append(
            "available_from = INFUR submissionDate (public knowability). "
            "Onset retained separately. No WAHIS API calls."
        )
        return output

    def _as_date(self, value: Any) -> date | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, date) and not isinstance(value, pd.Timestamp):
            return value
        ts = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(ts):
            return None
        return ts.date()

    def _within_cutoff(self, value: date | None) -> bool:
        return value is not None and value <= self.cutoff

    @staticmethod
    def _opt_str(value: Any) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _opt_int(value: Any) -> int | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _opt_float(value: Any) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
