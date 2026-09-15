"""Environmental features: weather turned into disease-specific suitability.

A raw temperature is not a risk factor. What matters epidemiologically is
whether conditions are favourable **for this pathogen, in this place, relative
to what is normal there** -- HPAI thrives in the cold wet conditions that
concentrate waterfowl, ASF persists where mild summers keep virus viable in
carcasses and wild boar active.

Three transformations are applied, in this order:

1. **Anomaly**: observed weekly weather minus the WorldClim monthly normal for
   that country. This removes the geographic baseline so that "cold" means
   "cold for here".
2. **Suitability**: a Gaussian thermal response around the disease optimum,
   modulated by precipitation and, for HPAI, a cold-anomaly term.
3. **Persistence**: a 4-week trailing mean of suitability, because a single
   favourable week rarely establishes transmission.

Availability is inherited from the underlying ERA5 record, so the derived
feature can never be knowable before its inputs were published.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.config import DiseaseSpec, load_countries, load_diseases
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["build_environmental_features"]

_FAMILY = "environmental"


def build_environmental_features(covariates: pd.DataFrame) -> pd.DataFrame:
    """Return long feature-store rows for the environmental family."""
    if covariates.empty:
        return pd.DataFrame()

    countries = load_countries()
    diseases = load_diseases()

    weather = covariates.loc[
        covariates["variable"].isin(
            [
                "t2m_mean_c", "t2m_min_c", "t2m_max_c",
                "total_precipitation_mm", "relative_humidity_pct",
                "soil_temperature_l1_c", "volumetric_soil_water_l1", "snow_depth_m",
            ]
        )
    ].copy()
    if weather.empty:
        LOGGER.warning("No weather covariates found; environmental features will be empty.")
        return pd.DataFrame()

    wide = weather.pivot_table(
        index=["country_iso3", "reference_week"],
        columns="variable",
        values="value",
        aggfunc="last",
    ).reset_index()
    availability = (
        weather.groupby(["country_iso3", "reference_week"], as_index=False)["available_from"].max()
    )
    wide = wide.merge(availability, on=["country_iso3", "reference_week"], how="left")
    wide["month"] = pd.to_datetime(wide["reference_week"]).dt.month

    normals = _worldclim_normals(covariates)
    wide = wide.merge(normals, on=["country_iso3", "month"], how="left")

    # --- anomalies against the long-term normal ------------------------- #
    wide["temp_anomaly_c"] = wide["t2m_mean_c"] - wide["normal_tavg_c"]
    wide["precip_anomaly_mm"] = wide["total_precipitation_mm"] - wide["normal_prec_mm"] / 4.33
    wide["cold_snap_index"] = np.clip(-wide["temp_anomaly_c"], 0.0, None)

    rows: list[pd.DataFrame] = []
    for code, disease in diseases.items():
        block = wide.copy()
        block["suitability"] = _suitability(block, disease)
        block = block.sort_values(["country_iso3", "reference_week"])
        block["suitability_4w"] = (
            block.groupby("country_iso3")["suitability"]
            .transform(lambda s: s.rolling(4, min_periods=1).mean())
        )
        block["suitability_trend"] = (
            block.groupby("country_iso3")["suitability"].transform(lambda s: s.diff(4))
        ).fillna(0.0)
        block["entity_key"] = block["country_iso3"] + "|" + code
        block["disease"] = code

        emitted = {
            "env_suitability": "suitability",
            "env_suitability_4w": "suitability_4w",
            "env_suitability_trend": "suitability_trend",
            "env_temp_anomaly_c": "temp_anomaly_c",
            "env_precip_anomaly_mm": "precip_anomaly_mm",
            "env_cold_snap_index": "cold_snap_index",
            "env_t2m_mean_c": "t2m_mean_c",
        }
        for feature_name, column in emitted.items():
            if column not in block.columns:
                continue
            piece = block[
                ["entity_key", "country_iso3", "disease", "reference_week", "available_from", column]
            ].rename(columns={column: "value"})
            piece["feature"] = feature_name
            piece["family"] = _FAMILY
            piece["source"] = "ERA5+WorldClim"
            rows.append(piece)

    out = pd.concat(rows, ignore_index=True)
    out = out.loc[out["value"].notna() & out["available_from"].notna()]
    LOGGER.info("Environmental features: %s rows across %s features",
                len(out), out["feature"].nunique())
    return out.reset_index(drop=True)


def _worldclim_normals(covariates: pd.DataFrame) -> pd.DataFrame:
    """Month-indexed climate normals, pivoted out of the static WorldClim rows."""
    normals = covariates.loc[covariates["variable"].str.startswith("worldclim_")].copy()
    if normals.empty:
        countries = load_countries()
        return pd.DataFrame(
            [
                {"country_iso3": iso, "month": month, "normal_tavg_c": np.nan, "normal_prec_mm": np.nan}
                for iso in countries
                for month in range(1, 13)
            ]
        )
    parts = normals["variable"].str.extract(r"worldclim_(?P<var>[a-z_]+)_m(?P<month>\d{2})")
    normals["var"] = parts["var"]
    normals["month"] = parts["month"].astype(int)
    pivot = normals.pivot_table(
        index=["country_iso3", "month"], columns="var", values="value", aggfunc="last"
    ).reset_index()
    rename = {"tavg_c": "normal_tavg_c", "prec_mm": "normal_prec_mm",
              "tmin_c": "normal_tmin_c", "tmax_c": "normal_tmax_c"}
    return pivot.rename(columns=rename)


def _suitability(frame: pd.DataFrame, disease: DiseaseSpec) -> pd.Series:
    """Disease-specific environmental suitability index in roughly [0, 2].

    Gaussian thermal response around the configured optimum, scaled by a
    precipitation modifier and a cold-anomaly term whose weight is
    disease-specific (material for HPAI, negligible for ASF).
    """
    env = disease.environment
    optimum = env.get("temp_optimum_c", 12.0)
    tolerance = max(env.get("temp_tolerance_c", 10.0), 1.0)

    temperature = frame["t2m_mean_c"].astype(float)
    thermal = np.exp(-0.5 * ((temperature - optimum) / tolerance) ** 2)

    precip = frame.get("total_precipitation_mm", pd.Series(0.0, index=frame.index)).astype(float)
    precip_z = (precip - precip.mean()) / (precip.std() + 1e-9)
    precip_term = np.clip(1.0 + env.get("precip_effect", 0.0) * precip_z, 0.4, 1.8)

    cold_term = np.clip(
        1.0 + env.get("cold_anomaly_weight", 0.0) * frame["cold_snap_index"].fillna(0.0) / 3.0,
        0.8, 2.2,
    )
    return (thermal * precip_term * cold_term).astype(float)
