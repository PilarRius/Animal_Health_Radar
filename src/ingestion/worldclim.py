"""WorldClim adapter - long-term climate normals.

WorldClim is a *static* product: monthly 1970-2000 normals that do not change
between analysis dates. Its role is not to describe current conditions but to
provide the denominator for them -- a 12 degree week means something very
different in Norway and in Egypt, and the anomaly is what carries the
epidemiological signal.

Because the product is static and long predates the analysis window, its
records are available from the first day of the panel. That is a genuine
statement about the data, not a convenience: no future information is embedded
in a 1970-2000 normal.
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.schemas.canonical import CovariateRecord
from src.schemas.enums import EvidenceCluster, SourceTier, SourceType
from src.utils.config import load_countries
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["WorldClimAdapter"]

_VARIABLES: dict[str, str] = {
    "tavg_c": "degC",
    "tmin_c": "degC",
    "tmax_c": "degC",
    "prec_mm": "mm/month",
}


class WorldClimAdapter(SourceAdapter):
    """Monthly climate normals used as the baseline for weather anomalies."""

    source_name = "WorldClim"
    source_type = SourceType.ENVIRONMENTAL
    source_tier = SourceTier.COVARIATE
    evidence_cluster = EvidenceCluster.ENVIRONMENTAL
    reliability = 0.92
    sample_filename = "worldclim_climatology_sample.csv"
    ingestion_lag_days = 0
    licence = "WorldClim - free for academic and non-commercial use"
    homepage = "https://www.worldclim.org"
    live_env_var = "WORLDCLIM_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries)]
        if frame.empty:
            output.notes.append("No WorldClim rows matched the configured panel.")
            return output

        # Static product: knowable from the very start of the analysis window.
        static_date = self.config.start_date

        for row in frame.to_dict(orient="records"):
            month = int(row["month"])
            provenance = self.make_provenance(
                record_id=f"WORLDCLIM-{row['iso3']}-m{month:02d}",
                published_at=static_date,
                available_from=static_date,
                query=f"worldclim:v2.1/monthly?country={row['iso3']}&month={month}",
                notes=str(row.get("reference_period", "long-term normals")),
            )
            for variable, unit in _VARIABLES.items():
                value = row.get(variable)
                if value is None or pd.isna(value):
                    continue
                output.covariates.append(
                    CovariateRecord(
                        covariate_id=f"worldclim_{variable}_m{month:02d}:{row['iso3']}",
                        country_iso3=row["iso3"],
                        disease=None,
                        reference_date=static_date,
                        available_from=static_date,
                        # Month encoded in the variable name: the record is static,
                        # so it has no meaningful reference date of its own.
                        variable=f"worldclim_{variable}_m{month:02d}",
                        value=float(value),
                        unit=unit,
                        aggregation="country_mean_of_normals",
                        provenance=provenance,
                    )
                )
            output.provenance.append(provenance)

        output.notes.append(
            "Static 1970-2000 normals; the month is encoded in the variable name so the "
            "record carries no time axis of its own and cannot leak."
        )
        return output
