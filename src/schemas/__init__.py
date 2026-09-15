"""Pydantic contracts for every object that crosses a module boundary."""

from src.schemas.canonical import (
    CanonicalEvent,
    CovariateRecord,
    EntityKey,
    SignalRecord,
    make_entity_key,
)
from src.schemas.enums import (
    AlertLevel,
    ConfirmationStatus,
    DataRealism,
    EventStatus,
    EvidenceCluster,
    HostCategory,
    SignalFamily,
    SourceTier,
    SourceType,
)
from src.schemas.outputs import (
    AlertObject,
    CounterfactualAblation,
    EvidenceContribution,
    Explanation,
    ForecastObject,
    NowcastObject,
    ReportingEstimate,
)
from src.schemas.provenance import ProvenanceLedgerEntry, SourceProvenance

__all__ = [
    "AlertLevel",
    "AlertObject",
    "CanonicalEvent",
    "ConfirmationStatus",
    "CounterfactualAblation",
    "CovariateRecord",
    "DataRealism",
    "EntityKey",
    "EventStatus",
    "EvidenceCluster",
    "EvidenceContribution",
    "Explanation",
    "ForecastObject",
    "HostCategory",
    "NowcastObject",
    "ProvenanceLedgerEntry",
    "ReportingEstimate",
    "SignalFamily",
    "SignalRecord",
    "SourceProvenance",
    "SourceTier",
    "SourceType",
    "make_entity_key",
]
