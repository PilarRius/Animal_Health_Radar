"""FAO EMPRES-i adapter.

EMPRES-i aggregates several streams, but for HPAI and ASF in the countries of
this pilot the overwhelming majority of records are **re-publications of WAHIS
notifications**. Counting them as independent corroboration would inflate both
the apparent evidence base and the apparent case counts.

The adapter therefore:

* stamps every record ``is_downstream_of_official=True`` and places it in the
  ``official`` evidence cluster, so the independence calculation treats it as
  the same voice as WAHIS;
* carries the upstream WAHIS identifier in ``provenance.derived_from`` so
  :mod:`src.linkage` can resolve the duplicate explicitly rather than by
  fuzzy matching;
* keeps the record anyway, because its *publication date* is genuinely
  informative: when EMPRES-i republishes faster than WAHIS disseminates, it
  moves the availability date earlier.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.schemas.canonical import CanonicalEvent
from src.schemas.enums import (
    ConfirmationStatus,
    EventStatus,
    EvidenceCluster,
    HostCategory,
    SourceTier,
    SourceType,
)
from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["EMPRESiAdapter"]


class EMPRESiAdapter(SourceAdapter):
    """FAO EMPRES-i records, explicitly marked as downstream of WAHIS."""

    source_name = "EMPRES-i"
    source_type = SourceType.OFFICIAL_DERIVED
    source_tier = SourceTier.SECONDARY_OFFICIAL
    evidence_cluster = EvidenceCluster.OFFICIAL
    reliability = 0.80
    downstream_of_official = True
    sample_filename = "empresi_events_sample.csv"
    ingestion_lag_days = 0
    licence = "FAO EMPRES-i terms of use"
    homepage = "https://empres-i.apps.fao.org"
    live_env_var = "EMPRESI_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        diseases = load_diseases()
        output = AdapterOutput(source_name=self.source_name)
        n_mirrored = 0

        for row in raw.to_dict(orient="records"):
            iso3 = str(row.get("iso3", "")).upper()
            disease_code = str(row.get("disease_code", "")).upper()
            if iso3 not in countries or disease_code not in diseases:
                continue

            published = self._as_date(row.get("published_date"))
            if not self._within_cutoff(published):
                continue

            upstream_ref = str(row.get("source_reference") or "").strip()
            upstream_source = str(row.get("upstream_source") or "").strip()
            derived_from = [ref for ref in (upstream_source, upstream_ref) if ref]
            if upstream_ref:
                n_mirrored += 1

            provenance = self.make_provenance(
                record_id=str(row.get("empresi_id")),
                published_at=published,
                url=f"{self.homepage}/#/event/{row.get('empresi_id')}",
                query=f"empresi:event:{row.get('empresi_id')}",
                derived_from=derived_from,
                notes=(
                    "Re-publication of a WAHIS notification; excluded from official "
                    "burden counts and discounted in the evidence-independence score."
                ),
            )

            event = CanonicalEvent(
                event_id=str(row.get("empresi_id")),
                source_event_id=upstream_ref or None,
                disease=disease_code,
                disease_raw=str(row.get("disease")) if row.get("disease") is not None else None,
                species=[s for s in str(row.get("species", "")).split(";") if s],
                host_category=HostCategory.UNKNOWN,
                country_iso3=iso3,
                country_name=countries[iso3].name,
                latitude=self._float(row.get("latitude")),
                longitude=self._float(row.get("longitude")),
                location_precision="point",
                onset_date=self._as_date(row.get("observation_date")),
                notification_date=self._as_date(row.get("report_date")),
                publication_date=published,
                outbreaks=1,
                cases=self._int(row.get("cases")),
                deaths=self._int(row.get("deaths")),
                event_status=EventStatus.CONFIRMED,
                confirmation_status=ConfirmationStatus.LABORATORY_CONFIRMED,
                available_from=published,
                provenance=provenance,
                extras={"upstream_reference": upstream_ref, "upstream_source": upstream_source},
            )
            output.events.append(event)
            output.provenance.append(provenance)

        output.notes.append(
            f"{n_mirrored} of {len(output.events)} EMPRES-i records carry an explicit WAHIS "
            "reference and are resolved to the same canonical event by src.linkage."
        )
        return output

    @staticmethod
    def _float(value: object) -> float | None:
        try:
            out = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return None if pd.isna(out) else out

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            out = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return None if pd.isna(out) else int(out)
