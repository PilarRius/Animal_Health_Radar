"""Livestock exposure features.

Exposure is the denominator that gives a signal its consequence. It enters the
model in three forms:

``exp_host_density_log``
    Log density of the host species relevant to the disease (chickens for HPAI,
    pigs for ASF). Log scale because risk responds to orders of magnitude, not
    to absolute head counts.
``exp_host_density_rank``
    The country's rank among the panel, computed **using only vintages already
    released at that point**. A percentile computed over the whole file would
    quietly embed future releases.
``exp_stock_trend``
    Year-on-year change in national stocks from FAOSTAT: a herd that is growing
    fast is an expanding susceptible population.

All three inherit the release date of the underlying vintage, so a 2020 GLW
layer published in 2022 is invisible to a 2021 prediction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.config import load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["build_exposure_features"]

_FAMILY = "livestock_exposure"

#: Disease exposure layer -> GLW species column.
_SPECIES_FOR_LAYER = {"chickens_density": "chickens", "pigs_density": "pigs"}


def build_exposure_features(covariates: pd.DataFrame) -> pd.DataFrame:
    """Return long feature-store rows for the exposure family."""
    if covariates.empty:
        return pd.DataFrame()

    countries = load_countries()
    diseases = load_diseases()
    rows: list[pd.DataFrame] = []

    density = covariates.loc[covariates["variable"].str.endswith("_density")].copy()
    stocks = covariates.loc[covariates["variable"].str.startswith("faostat_")].copy()

    for code, disease in diseases.items():
        species = _SPECIES_FOR_LAYER.get(disease.exposure_layer, "cattle")

        # --- gridded density, vintage by vintage -------------------------- #
        block = density.loc[density["variable"] == f"{species}_density"].copy()
        if not block.empty:
            block["value"] = pd.to_numeric(block["value"], errors="coerce")
            block["log_density"] = np.log1p(block["value"].clip(lower=0.0))

            # Rank within each release vintage only.
            block["rank_within_vintage"] = block.groupby("available_from")["log_density"].rank(
                pct=True
            )
            for feature_name, column in (
                ("exp_host_density_log", "log_density"),
                ("exp_host_density_rank", "rank_within_vintage"),
            ):
                piece = block[
                    ["country_iso3", "reference_week", "available_from", column]
                ].rename(columns={column: "value"})
                piece["entity_key"] = piece["country_iso3"] + "|" + code
                piece["disease"] = code
                piece["feature"] = feature_name
                piece["family"] = _FAMILY
                piece["source"] = "GLW4"
                rows.append(piece)

        # --- national stocks and their trend ------------------------------ #
        stock_block = stocks.loc[stocks["variable"] == f"faostat_{species}_stocks"].copy()
        if not stock_block.empty:
            stock_block = stock_block.sort_values(["country_iso3", "reference_week"])
            stock_block["value"] = pd.to_numeric(stock_block["value"], errors="coerce")
            stock_block["log_stock"] = np.log1p(stock_block["value"].clip(lower=0.0))
            stock_block["stock_trend"] = (
                stock_block.groupby("country_iso3")["log_stock"].diff().fillna(0.0)
            )
            for feature_name, column in (
                ("exp_national_stock_log", "log_stock"),
                ("exp_stock_trend", "stock_trend"),
            ):
                piece = stock_block[
                    ["country_iso3", "reference_week", "available_from", column]
                ].rename(columns={column: "value"})
                piece["entity_key"] = piece["country_iso3"] + "|" + code
                piece["disease"] = code
                piece["feature"] = feature_name
                piece["family"] = _FAMILY
                piece["source"] = "FAOSTAT"
                rows.append(piece)

    if not rows:
        LOGGER.warning("No exposure covariates matched the configured diseases.")
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    out = out.loc[out["value"].notna() & np.isfinite(out["value"])]
    keep = ["entity_key", "country_iso3", "disease", "reference_week",
            "feature", "value", "available_from", "family", "source"]
    LOGGER.info("Exposure features: %s rows across %s features", len(out), out["feature"].nunique())
    return out[keep].reset_index(drop=True)
