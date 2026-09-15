"""Canonical representations of everything that enters the system.

Three record types cover all adapters:

:class:`CanonicalEvent`
    An assertion that disease activity occurred at a place and time. Official
    notifications *and* unverified media signals both normalise to this shape;
    they are distinguished by ``confirmation_status`` and provenance, never by
    living in different tables. This is what makes it possible to reason about
    the observation process explicitly.

:class:`SignalRecord`
    A non-event quantitative signal attached to a country/disease/period
    (media volume, source diversity, acceleration, aggregator counts).

:class:`CovariateRecord`
    Environmental, exposure or contextual covariates attached to a country and
    period. Not an observation of disease.

The critical shared field is ``available_from``: the earliest date the record
may legally influence any prediction.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from src.schemas.enums import (
    ConfirmationStatus,
    DataRealism,
    EventStatus,
    HostCategory,
    SignalFamily,
)
from src.schemas.provenance import SourceProvenance

__all__ = ["CanonicalEvent", "SignalRecord", "CovariateRecord", "EntityKey", "make_entity_key"]


def make_entity_key(country_iso3: str, disease: str) -> str:
    """The unit of analysis for the whole system: one country x one disease."""
    return f"{country_iso3.upper()}|{disease.upper()}"


class EntityKey(BaseModel):
    """Structured form of the ``COUNTRY|DISEASE`` analysis unit."""

    model_config = ConfigDict(frozen=True)

    country_iso3: str
    disease: str

    @property
    def key(self) -> str:
        return make_entity_key(self.country_iso3, self.disease)


class CanonicalEvent(BaseModel):
    """A single asserted disease-activity event, from any source.

    Timeline fields follow the causal chain. They are all optional because the
    whole point of the system is that most of them are missing most of the time:

    ``onset_date`` -> ``suspicion_date`` -> ``confirmation_date``
    -> ``notification_date`` -> ``publication_date``
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # --- identity ---------------------------------------------------------- #
    event_id: str = Field(..., description="Unique id within the source system.")
    canonical_event_id: str | None = Field(
        None, description="Cluster id assigned by entity resolution across sources."
    )
    source_event_id: str | None = Field(None, description="Native id in the origin system.")

    # --- what -------------------------------------------------------------- #
    disease: str = Field(..., description="Normalised disease code (HPAI, ASF, ...).")
    disease_raw: str | None = Field(None, description="Disease string as published.")
    serotype: str | None = None
    species: list[str] = Field(default_factory=list)
    host_category: HostCategory = HostCategory.UNKNOWN

    # --- where ------------------------------------------------------------- #
    country_iso3: str = Field(..., min_length=3, max_length=3)
    country_name: str | None = None
    admin1: str | None = Field(None, description="First-level administrative unit.")
    locality: str | None = None
    latitude: float | None = Field(None, ge=-90.0, le=90.0)
    longitude: float | None = Field(None, ge=-180.0, le=180.0)
    location_precision: str | None = Field(
        None, description="point | admin1 | country | unknown"
    )

    # --- when (the observation process, made explicit) --------------------- #
    onset_date: date | None = Field(None, description="Start of the event in the world.")
    suspicion_date: date | None = Field(None, description="First veterinary suspicion.")
    confirmation_date: date | None = Field(None, description="Laboratory confirmation.")
    notification_date: date | None = Field(None, description="Notification to WOAH.")
    publication_date: date | None = Field(None, description="Public availability.")
    resolved_date: date | None = None

    # --- magnitude --------------------------------------------------------- #
    outbreaks: int | None = Field(None, ge=0, description="Number of outbreaks/foci.")
    cases: int | None = Field(None, ge=0)
    deaths: int | None = Field(None, ge=0)
    killed_disposed: int | None = Field(None, ge=0)
    susceptible: int | None = Field(None, ge=0)

    # --- status ------------------------------------------------------------ #
    event_status: EventStatus = EventStatus.UNKNOWN
    confirmation_status: ConfirmationStatus = ConfirmationStatus.UNVERIFIED_SIGNAL
    is_first_occurrence: bool = Field(
        False, description="First occurrence of the disease in the country/zone."
    )
    report_type: str | None = Field(None, description="immediate | follow_up | six_monthly")
    report_number: int | None = Field(None, ge=0)

    # --- point-in-time ------------------------------------------------------ #
    available_from: date = Field(
        ..., description="Date from which this record may influence any prediction."
    )

    # --- provenance --------------------------------------------------------- #
    provenance: SourceProvenance

    # --- free-form ---------------------------------------------------------- #
    summary: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    # --- validators --------------------------------------------------------- #
    @field_validator("country_iso3")
    @classmethod
    def _upper_iso(cls, value: str) -> str:
        return value.upper()

    @field_validator("disease")
    @classmethod
    def _upper_disease(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "onset_date", "suspicion_date", "confirmation_date",
        "notification_date", "publication_date", "resolved_date",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if value in (None, "", "NaT", "nan"):
            return None
        return value

    @model_validator(mode="after")
    def _check_causal_order(self) -> CanonicalEvent:
        """The observation chain must be monotone; sources sometimes are not.

        Rather than dropping the record we record the inconsistency in
        ``extras`` so that data-quality issues remain visible downstream.
        """
        chain = [
            ("onset_date", self.onset_date),
            ("suspicion_date", self.suspicion_date),
            ("confirmation_date", self.confirmation_date),
            ("notification_date", self.notification_date),
            ("publication_date", self.publication_date),
        ]
        present = [(name, value) for name, value in chain if value is not None]
        violations = [
            f"{present[i][0]}>{present[i + 1][0]}"
            for i in range(len(present) - 1)
            if present[i][1] > present[i + 1][1]
        ]
        if violations:
            self.extras.setdefault("timeline_violations", violations)

        # Availability can never precede the moment the fact was published.
        if self.publication_date is not None and self.available_from < self.publication_date:
            raise ValueError(
                f"available_from ({self.available_from}) precedes publication_date "
                f"({self.publication_date}) for event {self.event_id}: this would leak."
            )
        return self

    # --- derived ------------------------------------------------------------ #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def entity_key(self) -> str:
        return make_entity_key(self.country_iso3, self.disease)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reporting_delay_days(self) -> int | None:
        """``notification_date - onset_date`` in days, the delay-model target."""
        if self.onset_date is None or self.notification_date is None:
            return None
        return (self.notification_date - self.onset_date).days

    @computed_field  # type: ignore[prop-decorator]
    @property
    def detection_delay_days(self) -> int | None:
        """``suspicion_date - onset_date``: the surveillance-sensitivity component."""
        if self.onset_date is None or self.suspicion_date is None:
            return None
        return (self.suspicion_date - self.onset_date).days

    @computed_field  # type: ignore[prop-decorator]
    @property
    def publication_delay_days(self) -> int | None:
        """``publication_date - notification_date``: the dissemination component."""
        if self.notification_date is None or self.publication_date is None:
            return None
        return (self.publication_date - self.notification_date).days

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reference_date(self) -> date:
        """Best available estimate of when the event actually happened."""
        for candidate in (
            self.onset_date,
            self.suspicion_date,
            self.confirmation_date,
            self.notification_date,
            self.publication_date,
        ):
            if candidate is not None:
                return candidate
        return self.available_from

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_official(self) -> bool:
        return self.confirmation_status in (
            ConfirmationStatus.LABORATORY_CONFIRMED,
            ConfirmationStatus.CLINICALLY_SUSPECTED,
        ) and not self.provenance.is_downstream_of_official

    def to_flat(self) -> dict[str, Any]:
        """Flatten for the interim Parquet event table."""
        row: dict[str, Any] = {
            "event_id": self.event_id,
            "canonical_event_id": self.canonical_event_id,
            "source_event_id": self.source_event_id,
            "entity_key": self.entity_key,
            "disease": self.disease,
            "disease_raw": self.disease_raw,
            "serotype": self.serotype,
            "species": ";".join(self.species),
            "host_category": str(self.host_category),
            "country_iso3": self.country_iso3,
            "country_name": self.country_name,
            "admin1": self.admin1,
            "locality": self.locality,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "location_precision": self.location_precision,
            "onset_date": self.onset_date,
            "suspicion_date": self.suspicion_date,
            "confirmation_date": self.confirmation_date,
            "notification_date": self.notification_date,
            "publication_date": self.publication_date,
            "resolved_date": self.resolved_date,
            "reference_date": self.reference_date,
            "available_from": self.available_from,
            "outbreaks": self.outbreaks,
            "cases": self.cases,
            "deaths": self.deaths,
            "killed_disposed": self.killed_disposed,
            "susceptible": self.susceptible,
            "event_status": str(self.event_status),
            "confirmation_status": str(self.confirmation_status),
            "is_first_occurrence": self.is_first_occurrence,
            "report_type": self.report_type,
            "report_number": self.report_number,
            "reporting_delay_days": self.reporting_delay_days,
            "detection_delay_days": self.detection_delay_days,
            "publication_delay_days": self.publication_delay_days,
            "is_official": self.is_official,
            "summary": self.summary,
        }
        prov = self.provenance
        row.update(
            {
                "source_name": prov.source_name,
                "source_type": str(prov.source_type),
                "source_tier": str(prov.source_tier),
                "evidence_cluster": str(prov.evidence_cluster),
                "is_downstream_of_official": prov.is_downstream_of_official,
                "realism": str(prov.realism),
                "reliability": prov.reliability,
                "provenance_id": prov.fingerprint(),
            }
        )
        return row


class SignalRecord(BaseModel):
    """A quantitative non-event signal for a country/disease/period.

    Media adapters emit *derived* quantities (abnormal volume, source
    diversity, acceleration), never raw article counts interpreted as
    probabilities.
    """

    model_config = ConfigDict(extra="forbid")

    signal_id: str
    country_iso3: str = Field(..., min_length=3, max_length=3)
    disease: str
    reference_date: date = Field(..., description="Start of the period described.")
    available_from: date
    signal_name: str = Field(..., description="e.g. 'gdelt_abnormal_volume'.")
    signal_family: SignalFamily
    value: float
    unit: str | None = None
    denominator: float | None = Field(
        None, description="Baseline used to derive an anomaly, when applicable."
    )
    provenance: SourceProvenance

    @field_validator("country_iso3")
    @classmethod
    def _upper_iso(cls, value: str) -> str:
        return value.upper()

    @field_validator("disease")
    @classmethod
    def _upper_disease(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _no_leak(self) -> SignalRecord:
        if self.available_from < self.reference_date:
            raise ValueError(
                f"Signal {self.signal_id}: available_from {self.available_from} precedes its "
                f"own reference_date {self.reference_date}."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entity_key(self) -> str:
        return make_entity_key(self.country_iso3, self.disease)

    def to_flat(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "entity_key": self.entity_key,
            "country_iso3": self.country_iso3,
            "disease": self.disease,
            "reference_date": self.reference_date,
            "available_from": self.available_from,
            "signal_name": self.signal_name,
            "signal_family": str(self.signal_family),
            "value": self.value,
            "unit": self.unit,
            "denominator": self.denominator,
            "source_name": self.provenance.source_name,
            "source_type": str(self.provenance.source_type),
            "evidence_cluster": str(self.provenance.evidence_cluster),
            "realism": str(self.provenance.realism),
            "reliability": self.provenance.reliability,
            "provenance_id": self.provenance.fingerprint(),
        }


class CovariateRecord(BaseModel):
    """Environmental / exposure / contextual covariate for a country-period.

    Disease-agnostic by default (``disease=None``); the feature builders derive
    disease-specific suitability from these raw covariates.
    """

    model_config = ConfigDict(extra="forbid")

    covariate_id: str
    country_iso3: str = Field(..., min_length=3, max_length=3)
    disease: str | None = None
    reference_date: date
    available_from: date
    variable: str = Field(..., description="e.g. 't2m_mean_c', 'pigs_density'.")
    value: float
    unit: str | None = None
    aggregation: str = Field("country_mean", description="How gridded data was aggregated.")
    provenance: SourceProvenance

    @field_validator("country_iso3")
    @classmethod
    def _upper_iso(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _no_leak(self) -> CovariateRecord:
        if self.available_from < self.reference_date:
            raise ValueError(
                f"Covariate {self.covariate_id}: available_from precedes reference_date."
            )
        return self

    def to_flat(self) -> dict[str, Any]:
        return {
            "covariate_id": self.covariate_id,
            "country_iso3": self.country_iso3,
            "disease": self.disease,
            "reference_date": self.reference_date,
            "available_from": self.available_from,
            "variable": self.variable,
            "value": self.value,
            "unit": self.unit,
            "aggregation": self.aggregation,
            "source_name": self.provenance.source_name,
            "source_type": str(self.provenance.source_type),
            "evidence_cluster": str(self.provenance.evidence_cluster),
            "realism": str(self.provenance.realism),
            "provenance_id": self.provenance.fingerprint(),
        }


def assert_corpus_is_labelled(records: list[CanonicalEvent]) -> dict[str, int]:
    """Count records by realism label - used by the app to display a data banner."""
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.provenance.realism)
        counts[key] = counts.get(key, 0) + 1
    if DataRealism.REAL.value not in counts and not counts:
        raise ValueError("Empty corpus: nothing to label.")
    return counts
