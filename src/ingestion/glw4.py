"""Gridded Livestock of the World (GLW) adapter - exposure denominators.

Host density is the contextual layer that turns "a signal" into "a signal that
matters": the same intelligence chatter means something different in a region
with two million pigs per degree square than in one with two thousand.

Two details are handled explicitly:

**Vintages.** GLW is released in discrete versions (GLW3 for reference year
2010, GLW4 for 2020), each published years after its reference year. The
adapter emits both with their true release dates, so the point-in-time store
selects the version that actually existed at each as-of date instead of
retro-fitting today's numbers onto 2021.

**Exposure is not risk.** The adapter emits densities, not scores. Converting
density into a standardised exposure feature is the feature layer's job.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.schemas.canonical import CovariateRecord
from src.schemas.enums import EvidenceCluster, SourceTier, SourceType
from src.utils.config import load_countries
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["GLW4Adapter"]


class GLW4Adapter(SourceAdapter):
    """Country-aggregated livestock densities with release-vintage awareness."""

    source_name = "GLW4"
    source_type = SourceType.EXPOSURE
    source_tier = SourceTier.COVARIATE
    evidence_cluster = EvidenceCluster.EXPOSURE
    reliability = 0.85
    sample_filename = "glw4_livestock_density_sample.csv"
    ingestion_lag_days = 0
    licence = "CC BY 4.0 (Harvard Dataverse)"
    homepage = "https://dataverse.harvard.edu/dataverse/glw"
    live_env_var = "GLW4_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries)]
        if frame.empty:
            output.notes.append("No GLW rows matched the configured panel.")
            return output

        n_vintages = 0
        for row in frame.to_dict(orient="records"):
            ref_year = int(row.get("reference_year", 2020))
            reference = date(ref_year, 1, 1)
            release = self._as_date(row.get("release_date")) or date(ref_year + 2, 1, 1)
            if release > self.cutoff:
                continue
            n_vintages += 1

            species = str(row["species"])
            version = str(row.get("dataset_version", "GLW4"))
            provenance = self.make_provenance(
                record_id=f"{version}-{row['iso3']}-{species}-{ref_year}",
                published_at=release,
                available_from=release,
                query=f"glw:{version}?country={row['iso3']}&species={species}",
                notes=f"{version} reference year {ref_year}, released {release.isoformat()}.",
            )
            for variable, value, unit in (
                (f"{species}_density", row.get("density_head_per_km2"), "head/km2"),
                (f"{species}_total_head", row.get("total_head"), "head"),
            ):
                if value is None or pd.isna(value):
                    continue
                output.covariates.append(
                    CovariateRecord(
                        covariate_id=f"{variable}:{row['iso3']}:{ref_year}",
                        country_iso3=row["iso3"],
                        disease=None,
                        reference_date=reference,
                        available_from=release,
                        variable=variable,
                        value=float(value),
                        unit=unit,
                        aggregation=str(row.get("aggregation", "country_sum_of_grid_cells")),
                        provenance=provenance,
                    )
                )
            output.provenance.append(provenance)

        output.notes.append(
            f"{n_vintages} vintage record(s) available at the cut-off. The feature store "
            "selects the most recent vintage released on or before each as-of date."
        )
        return output
