"""ERA5 and ERA5-Land adapters - meteorological covariates.

Reanalysis is the one input in this system that is genuinely independent of the
epidemiological reporting process: whether or not a country notifies an
outbreak has no bearing on last week's temperature. That independence is what
makes environmental covariates valuable in the fusion model, and it is encoded
by placing them in their own evidence cluster.

The one thing that must not be forgotten is the **release lag**. ERA5 complete
fields are published about five days behind real time (ERA5T preliminary data
sooner). A prediction made on Monday cannot use last Thursday's reanalysis.
``config/config.yaml: features.availability_lag_days.environmental`` sets that
lag and the adapter applies it on top of the end of the reference week.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from src.ingestion.base import AdapterOutput, SourceAdapter
from src.schemas.canonical import CovariateRecord
from src.schemas.enums import EvidenceCluster, SourceTier, SourceType
from src.utils.config import load_countries
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["ERA5Adapter", "ERA5LandAdapter"]


class _WeeklyReanalysisAdapter(SourceAdapter):
    """Shared machinery for weekly country-aggregated reanalysis products."""

    source_type = SourceType.ENVIRONMENTAL
    source_tier = SourceTier.COVARIATE
    evidence_cluster = EvidenceCluster.ENVIRONMENTAL
    reliability = 0.90
    live_env_var = "CDSAPI_KEY"

    #: Columns to emit as covariates, mapped to their unit.
    variables: dict[str, str] = {}

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries)]
        if frame.empty:
            output.notes.append(f"No {self.source_name} rows matched the configured panel.")
            return output

        configured_lag = int(self.config.get("features.availability_lag_days.environmental", 6))
        n_withheld = 0

        for row in frame.to_dict(orient="records"):
            week_start = self._as_date(row.get("week_start"))
            if week_start is None:
                continue
            # The weekly aggregate only exists once the week has ended.
            week_end = week_start + timedelta(days=6)
            lag = int(row.get("release_lag_days", configured_lag) or configured_lag)
            available = week_end + timedelta(days=lag)
            if available > self.cutoff:
                n_withheld += 1
                continue

            provenance = self.make_provenance(
                record_id=f"{self.source_name}-{row['iso3']}-{week_start}",
                published_at=available,
                available_from=available,
                query=f"{self.source_name.lower()}:weekly?country={row['iso3']}&week={week_start}",
                notes=f"Country area-weighted mean; release lag {lag} days after week end.",
            )
            for variable, unit in self.variables.items():
                value = row.get(variable)
                if value is None or pd.isna(value):
                    continue
                output.covariates.append(
                    CovariateRecord(
                        covariate_id=f"{variable}:{row['iso3']}:{week_start}",
                        country_iso3=row["iso3"],
                        disease=None,
                        reference_date=week_start,
                        available_from=available,
                        variable=variable,
                        value=float(value),
                        unit=unit,
                        aggregation=str(row.get("aggregation", "country_area_weighted_mean")),
                        provenance=provenance,
                    )
                )
            output.provenance.append(provenance)

        if n_withheld:
            output.notes.append(
                f"{n_withheld} week(s) withheld: the reanalysis release date falls after the "
                f"corpus cut-off ({self.cutoff}). Recent weeks are genuinely unavailable."
            )
        output.notes.append(
            "Environmental covariates are independent of the reporting process and form "
            "their own evidence cluster."
        )
        return output


class ERA5Adapter(_WeeklyReanalysisAdapter):
    """ERA5 single-level weekly aggregates."""

    source_name = "ERA5"
    sample_filename = "era5_weekly_sample.csv"
    licence = "Copernicus Climate Change Service - free with attribution"
    homepage = "https://cds.climate.copernicus.eu"
    variables = {
        "t2m_mean_c": "degC",
        "t2m_min_c": "degC",
        "t2m_max_c": "degC",
        "total_precipitation_mm": "mm/week",
        "relative_humidity_pct": "%",
        "wind_speed_10m_ms": "m/s",
    }


class ERA5LandAdapter(_WeeklyReanalysisAdapter):
    """ERA5-Land surface and soil variables at finer resolution.

    Kept separate from :class:`ERA5Adapter` because the products have different
    release schedules and resolutions, but placed in the same evidence cluster:
    they are not independent of each other.
    """

    source_name = "ERA5-Land"
    sample_filename = "era5land_weekly_sample.csv"
    licence = "Copernicus Climate Change Service - free with attribution"
    homepage = "https://cds.climate.copernicus.eu"
    reliability = 0.88
    variables = {
        "skin_temperature_c": "degC",
        "soil_temperature_l1_c": "degC",
        "volumetric_soil_water_l1": "m3/m3",
        "snow_depth_m": "m",
    }
