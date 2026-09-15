"""Adapter base class and shared contract.

Every source, however different its wire format, exposes the same three-step
contract::

    load_raw()   -> pandas.DataFrame   # exactly what the source publishes
    transform()  -> AdapterOutput      # canonical events / signals / covariates
    run()        -> AdapterOutput      # load_raw + transform + provenance

Design rules enforced here
--------------------------
* **Provenance is mandatory.** ``make_provenance`` is the only way to stamp a
  record, and it always sets a realism label.
* **Availability is mandatory.** Nothing leaves an adapter without an
  ``available_from`` date, so downstream point-in-time filtering can be
  verified rather than trusted.
* **Unavailable data is never invented.** In ``live`` mode an adapter without a
  configured endpoint raises :class:`LiveSourceUnavailable` describing exactly
  what is missing. It never silently falls back to synthetic data.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.schemas.canonical import CanonicalEvent, CovariateRecord, SignalRecord
from src.schemas.enums import DataRealism, EvidenceCluster, SourceTier, SourceType
from src.schemas.provenance import SourceProvenance
from src.utils.config import AppConfig, get_config
from src.utils.io import read_csv
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "AdapterOutput",
    "SourceAdapter",
    "LiveSourceUnavailable",
]


class LiveSourceUnavailable(RuntimeError):
    """Raised when live mode is requested but the source is not configured.

    Deliberately explicit: the alternative -- quietly returning synthetic rows
    while claiming to be live -- would corrupt every downstream conclusion.
    """


@dataclass
class AdapterOutput:
    """Everything one adapter contributes to the corpus."""

    source_name: str
    events: list[CanonicalEvent] = field(default_factory=list)
    signals: list[SignalRecord] = field(default_factory=list)
    covariates: list[CovariateRecord] = field(default_factory=list)
    provenance: list[SourceProvenance] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        return len(self.events) + len(self.signals) + len(self.covariates)

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source_name,
            "events": len(self.events),
            "signals": len(self.signals),
            "covariates": len(self.covariates),
            "notes": self.notes,
        }


class SourceAdapter(ABC):
    """Base class for all data source adapters."""

    #: Canonical source label, used as the provenance ``source_name``.
    source_name: str = "UNKNOWN"
    source_type: SourceType = SourceType.CONTEXTUAL
    source_tier: SourceTier = SourceTier.COVARIATE
    evidence_cluster: EvidenceCluster = EvidenceCluster.UNKNOWN

    #: Prior weight on this source's assertions, used by evidence fusion.
    reliability: float = 0.5

    #: True when the source merely republishes an official notification.
    downstream_of_official: bool = False

    #: File in ``data/sample`` backing this adapter in sample mode.
    sample_filename: str = ""

    #: Realism label applied to every record produced in sample mode.
    sample_realism: DataRealism = DataRealism.SYNTHETIC

    #: Extra days between the source's own publication date and the moment the
    #: pipeline could realistically have ingested it.
    ingestion_lag_days: int = 0

    licence: str | None = None
    homepage: str | None = None
    #: Environment variable that must be set for live mode to be possible.
    live_env_var: str | None = None

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.cutoff: date = self.config.data_cutoff
        self._raw: pd.DataFrame | None = None

    # ------------------------------------------------------------------ #
    # loading
    # ------------------------------------------------------------------ #
    @property
    def sample_path(self) -> Path:
        return self.config.path("data_sample") / self.sample_filename

    def load_raw(self) -> pd.DataFrame:
        """Return the source's records exactly as published."""
        if self.config.data_mode == "live":
            return self.fetch_live()
        if not self.sample_filename:
            raise LiveSourceUnavailable(
                f"{self.source_name}: no sample file configured and data_mode is not 'live'."
            )
        frame = read_csv(self.sample_path)
        LOGGER.debug("%s: loaded %s raw rows from %s", self.source_name, len(frame), self.sample_path.name)
        return frame

    def fetch_live(self) -> pd.DataFrame:
        """Fetch from the real source. Not enabled in this offline build."""
        missing = self.live_env_var or "<endpoint configuration>"
        configured = bool(self.live_env_var and os.environ.get(self.live_env_var))
        raise LiveSourceUnavailable(
            f"{self.source_name}: live ingestion is not implemented in this offline build.\n"
            f"  Required configuration: {missing} "
            f"({'present' if configured else 'missing'} in the environment)\n"
            f"  Homepage: {self.homepage or 'n/a'}\n"
            "  Set AHR_DATA_MODE=sample to use the labelled synthetic corpus instead. "
            "This adapter will never fabricate records and present them as real."
        )

    # ------------------------------------------------------------------ #
    # provenance
    # ------------------------------------------------------------------ #
    def make_provenance(
        self,
        record_id: str,
        *,
        published_at: date | None,
        available_from: date | None = None,
        url: str | None = None,
        query: str | None = None,
        derived_from: list[str] | None = None,
        realism: DataRealism | None = None,
        notes: str | None = None,
    ) -> SourceProvenance:
        """Stamp a record. The only sanctioned way to create provenance."""
        if available_from is None and published_at is not None:
            available_from = published_at + timedelta(days=self.ingestion_lag_days)
        return SourceProvenance(
            record_id=record_id,
            source_name=self.source_name,
            source_type=self.source_type,
            source_tier=self.source_tier,
            evidence_cluster=self.evidence_cluster,
            published_at=published_at,
            available_from=available_from,
            url=url or self.homepage,
            licence=self.licence,
            query=query,
            derived_from=derived_from or [],
            is_downstream_of_official=self.downstream_of_official,
            realism=realism or (
                self.sample_realism if self.config.data_mode == "sample" else DataRealism.REAL
            ),
            reliability=self.reliability,
            notes=notes,
        )

    # ------------------------------------------------------------------ #
    # transformation
    # ------------------------------------------------------------------ #
    @abstractmethod
    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        """Map raw records onto canonical schemas."""

    def run(self) -> AdapterOutput:
        """Load and transform, logging a one-line summary."""
        raw = self.load_raw()
        self._raw = raw
        output = self.transform(raw)
        if self.downstream_of_official:
            output.notes.append(
                f"{self.source_name} is downstream of WAHIS; its records are marked "
                "is_downstream_of_official=True and are excluded from official counts."
            )
        LOGGER.info(
            "%-12s -> %5d events | %5d signals | %5d covariates",
            self.source_name, len(output.events), len(output.signals), len(output.covariates),
        )
        return output

    # ------------------------------------------------------------------ #
    # helpers shared by concrete adapters
    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        """Metadata row for the source catalogue shown in the app."""
        return {
            "source_name": self.source_name,
            "source_type": str(self.source_type),
            "source_tier": str(self.source_tier),
            "evidence_cluster": str(self.evidence_cluster),
            "reliability": self.reliability,
            "downstream_of_official": self.downstream_of_official,
            "ingestion_lag_days": self.ingestion_lag_days,
            "licence": self.licence,
            "homepage": self.homepage,
            "sample_file": self.sample_filename or None,
            "realism": str(self.sample_realism),
        }

    @staticmethod
    def _as_date(value: Any) -> date | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        ts = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(ts) else ts.date()

    def _within_cutoff(self, value: date | None) -> bool:
        return value is not None and value <= self.cutoff
