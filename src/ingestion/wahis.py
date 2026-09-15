"""WOAH WAHIS adapter - the primary official observation process.

WAHIS is treated as the *reference observation*, never as the truth. Its role
in the system is threefold:

1. it supplies the officially visible burden, which the nowcast inflates;
2. its ``onset -> notification`` gaps are the training data for the reporting
   delay model;
3. its first notifications are the *labels* the early-warning model predicts.

The adapter is careful about one thing above all: ``available_from`` is the
**publication** date, not the notification or onset date. An outbreak that
started in March and was published in April did not exist, from the system's
point of view, until April.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
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
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["WAHISAdapter"]

_STATUS_MAP: dict[str, EventStatus] = {
    "ongoing": EventStatus.ONGOING,
    "resolved": EventStatus.RESOLVED,
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
    """Official immediate notifications and follow-up reports."""

    source_name = "WAHIS"
    source_type = SourceType.OFFICIAL
    source_tier = SourceTier.PRIMARY_OFFICIAL
    evidence_cluster = EvidenceCluster.OFFICIAL
    reliability = 0.95
    downstream_of_official = False
    sample_filename = "wahis_events_sample.csv"
    ingestion_lag_days = 0
    licence = "WOAH terms of use - attribution required"
    homepage = "https://wahis.woah.org"
    live_env_var = "WAHIS_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        diseases = load_diseases()
        known_iso = set(countries)
        known_disease = set(diseases)

        output = AdapterOutput(source_name=self.source_name)
        skipped_unknown = 0
        skipped_future = 0

        for row in raw.to_dict(orient="records"):
            iso3 = str(row.get("iso3", "")).upper()
            disease_code = str(row.get("disease_code", "")).upper()
            if iso3 not in known_iso or disease_code not in known_disease:
                skipped_unknown += 1
                continue

            publication = self._as_date(row.get("date_of_publication"))
            if not self._within_cutoff(publication):
                # Not yet public at the corpus cut-off => does not exist for us.
                skipped_future += 1
                continue

            provenance = self.make_provenance(
                record_id=str(row.get("outbreak_id") or row.get("event_id")),
                published_at=publication,
                url=f"{self.homepage}/#/event/{row.get('event_id')}",
                query=f"wahis:event:{row.get('event_id')}",
                realism=DataRealism.SYNTHETIC
                if str(row.get("data_realism", "")).lower() == "synthetic"
                else None,
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
                event_status=_STATUS_MAP.get(str(row.get("event_status", "")).lower(), EventStatus.UNKNOWN),
                confirmation_status=_DIAGNOSIS_MAP.get(
                    str(row.get("diagnosis", "")).lower(), ConfirmationStatus.LABORATORY_CONFIRMED
                ),
                is_first_occurrence=bool(row.get("is_first_occurrence", False)),
                report_type=self._opt_str(row.get("report_type")),
                report_number=self._opt_int(row.get("report_number")),
                # THE critical line: knowable only once published.
                available_from=publication,
                provenance=provenance,
                summary=self._opt_str(row.get("control_measures")),
                extras={"control_measures": self._opt_str(row.get("control_measures"))},
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
                f"({self.cutoff}). These are genuinely unknown at analysis time."
            )
        output.notes.append(
            "available_from = date_of_publication. Onset and notification dates are "
            "retained but never used to decide what is knowable."
        )
        return output

    # -- small coercion helpers ------------------------------------------ #
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
