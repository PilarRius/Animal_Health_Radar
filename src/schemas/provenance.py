"""Provenance contract.

Every record that enters the system carries a :class:`SourceProvenance`. The
provenance object answers four questions that the epidemiology depends on:

1. **Who said it** (``source_name``, ``source_type``, ``source_tier``)
2. **When could we have known** (``published_at`` -> ``available_from``)
3. **Is it independent evidence** (``evidence_cluster``, ``derived_from``)
4. **Is it real** (``realism``) - synthetic and mock records are never
   silently presented as observations.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.enums import DataRealism, EvidenceCluster, SourceTier, SourceType

__all__ = ["SourceProvenance", "ProvenanceLedgerEntry"]


class SourceProvenance(BaseModel):
    """Where a single record came from and when it became knowable."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)

    # --- identity ---------------------------------------------------------- #
    record_id: str = Field(..., description="Stable id of the record within this source.")
    source_name: str = Field(..., description="Canonical source label, e.g. 'WAHIS'.")
    source_type: SourceType
    source_tier: SourceTier
    evidence_cluster: EvidenceCluster = EvidenceCluster.UNKNOWN

    # --- timing ------------------------------------------------------------ #
    published_at: date | None = Field(
        None, description="Date the source made the information public."
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now().replace(microsecond=0),
        description="When this pipeline fetched/generated the record.",
    )
    available_from: date | None = Field(
        None,
        description=(
            "Date from which the pipeline is allowed to use the record. "
            "Defaults to published_at; set later for sources with release lags."
        ),
    )

    # --- traceability ------------------------------------------------------ #
    url: str | None = None
    citation: str | None = None
    licence: str | None = Field(None, description="Licence/terms governing reuse.")
    query: str | None = Field(None, description="Query or file that produced the record.")

    # --- dependence -------------------------------------------------------- #
    derived_from: list[str] = Field(
        default_factory=list,
        description=(
            "Provenance record_ids or source names this record is downstream of. "
            "Used to prevent double-counting (EMPRES-i <- WAHIS)."
        ),
    )
    is_downstream_of_official: bool = Field(
        False,
        description="True when the record merely republishes an official notification.",
    )

    # --- quality ----------------------------------------------------------- #
    realism: DataRealism = Field(
        DataRealism.SYNTHETIC,
        description="real | synthetic | mock | derived. Never guessed.",
    )
    reliability: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Prior weight on this source's assertions (config-driven).",
    )
    notes: str | None = None

    # --- validators -------------------------------------------------------- #
    @field_validator("published_at", "available_from", mode="before")
    @classmethod
    def _coerce_dates(cls, value: Any) -> Any:
        if value in (None, "", "NaT"):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return date.fromisoformat(value[:10])
        return value

    @model_validator(mode="after")
    def _default_availability(self) -> SourceProvenance:
        if self.available_from is None and self.published_at is not None:
            object.__setattr__(self, "available_from", self.published_at)
        if self.available_from is not None and self.published_at is not None:
            if self.available_from < self.published_at:
                raise ValueError(
                    "available_from cannot precede published_at "
                    f"({self.available_from} < {self.published_at})."
                )
        return self

    # --- helpers ----------------------------------------------------------- #
    @property
    def is_synthetic(self) -> bool:
        """True for anything that is not a genuine fetch from the real source."""
        return self.realism in (DataRealism.SYNTHETIC, DataRealism.MOCK)

    def fingerprint(self) -> str:
        """Deterministic short hash identifying this provenance stamp."""
        payload = "|".join(
            [
                self.source_name,
                self.record_id,
                str(self.published_at),
                str(self.available_from),
            ]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def to_flat(self) -> dict[str, Any]:
        """Flat mapping suitable for a Parquet ledger row."""
        return {
            "provenance_id": self.fingerprint(),
            "record_id": self.record_id,
            "source_name": self.source_name,
            "source_type": str(self.source_type),
            "source_tier": str(self.source_tier),
            "evidence_cluster": str(self.evidence_cluster),
            "published_at": self.published_at,
            "available_from": self.available_from,
            "retrieved_at": self.retrieved_at,
            "url": self.url,
            "citation": self.citation,
            "licence": self.licence,
            "query": self.query,
            "derived_from": ";".join(self.derived_from),
            "is_downstream_of_official": self.is_downstream_of_official,
            "realism": str(self.realism),
            "reliability": self.reliability,
            "notes": self.notes,
        }


class ProvenanceLedgerEntry(BaseModel):
    """One row of the audit ledger written to ``data/processed/provenance.parquet``."""

    model_config = ConfigDict(extra="forbid")

    provenance_id: str
    stage: str = Field(..., description="Pipeline stage that emitted the record.")
    entity_key: str | None = Field(
        None, description="country_iso3|disease the record contributes to, if any."
    )
    n_records: int = Field(1, ge=0)
    provenance: SourceProvenance
