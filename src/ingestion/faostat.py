"""FAOSTAT adapter - annual national livestock statistics.

FAOSTAT is the slowest-moving input in the system and the clearest illustration
of why availability dates matter. Stocks for calendar year *Y* are typically
published around the middle of year *Y+1*. A forecast issued in March 2024
therefore has access to 2022 stocks, not 2023 ones.

The adapter stamps every record with its real release date and lets the
point-in-time store pick the latest vintage. Nothing in the pipeline is allowed
to reach for "the most recent year in the file".
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

__all__ = ["FAOSTATAdapter"]


class FAOSTATAdapter(SourceAdapter):
    """Annual livestock stocks with realistic publication lags."""

    source_name = "FAOSTAT"
    source_type = SourceType.CONTEXTUAL
    source_tier = SourceTier.COVARIATE
    evidence_cluster = EvidenceCluster.EXPOSURE
    reliability = 0.80
    sample_filename = "faostat_livestock_annual_sample.csv"
    licence = "CC BY-NC-SA 3.0 IGO"
    homepage = "https://www.fao.org/faostat"
    live_env_var = "FAOSTAT_API_BASE"

    def transform(self, raw: pd.DataFrame) -> AdapterOutput:
        countries = load_countries()
        output = AdapterOutput(source_name=self.source_name)

        frame = raw.copy()
        frame["iso3"] = frame["iso3"].astype(str).str.upper()
        frame = frame.loc[frame["iso3"].isin(countries)]
        if frame.empty:
            output.notes.append("No FAOSTAT rows matched the configured panel.")
            return output

        configured_lag = int(self.config.get("features.availability_lag_days.contextual", 365))
        n_pending = 0

        for row in frame.to_dict(orient="records"):
            year = int(row["year"])
            reference = date(year, 1, 1)
            release = self._as_date(row.get("release_date"))
            if release is None:
                release = date(year, 12, 31) + pd.Timedelta(days=configured_lag).to_pytimedelta()
            if release > self.cutoff:
                n_pending += 1
                continue

            item = str(row["item"])
            provenance = self.make_provenance(
                record_id=f"FAOSTAT-{row['iso3']}-{item}-{year}",
                published_at=release,
                available_from=release,
                query=f"faostat:QCL?area={row['iso3']}&item={item}&year={year}",
                notes=f"Stocks for {year}, released {release.isoformat()}.",
            )
            value = row.get("value")
            if value is None or pd.isna(value):
                continue
            output.covariates.append(
                CovariateRecord(
                    covariate_id=f"faostat_{item}_stocks:{row['iso3']}:{year}",
                    country_iso3=row["iso3"],
                    disease=None,
                    reference_date=reference,
                    available_from=release,
                    variable=f"faostat_{item}_stocks",
                    value=float(value) * 1000.0,   # file is in 1000 head
                    unit="head",
                    aggregation="national_total",
                    provenance=provenance,
                )
            )
            output.provenance.append(provenance)

        if n_pending:
            output.notes.append(
                f"{n_pending} annual record(s) withheld: not yet released at the cut-off "
                f"({self.cutoff}). The most recent usable year is therefore older than the "
                "most recent year present in the file."
            )
        return output
