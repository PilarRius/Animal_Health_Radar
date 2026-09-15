"""Lightweight geography helpers (no geopandas dependency).

The pilot works at country resolution, so great-circle distances between
country centroids plus a distance-decay kernel are sufficient to express
spatial spillover risk. The functions are written so that swapping in
polygon-based adjacency later only changes :func:`build_adjacency`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from src.utils.config import CountrySpec

__all__ = [
    "EARTH_RADIUS_KM",
    "haversine_km",
    "distance_matrix",
    "decay_kernel",
    "build_adjacency",
    "jitter_point",
]

EARTH_RADIUS_KM: float = 6371.0088


def haversine_km(
    lat1: float | np.ndarray, lon1: float | np.ndarray,
    lat2: float | np.ndarray, lon2: float | np.ndarray,
) -> np.ndarray:
    """Great-circle distance in kilometres."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = phi2 - phi1
    dlambda = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def distance_matrix(countries: Mapping[str, CountrySpec]) -> pd.DataFrame:
    """Symmetric centroid-to-centroid distance matrix (km), indexed by ISO3."""
    iso = list(countries.keys())
    lats = np.array([countries[c].lat for c in iso], dtype=float)
    lons = np.array([countries[c].lon for c in iso], dtype=float)
    out = np.zeros((len(iso), len(iso)), dtype=float)
    for i in range(len(iso)):
        out[i, :] = haversine_km(lats[i], lons[i], lats, lons)
    return pd.DataFrame(out, index=iso, columns=iso)


def decay_kernel(
    distances: pd.DataFrame,
    bandwidth_km: float = 900.0,
    *,
    shared_border: pd.DataFrame | None = None,
    border_bonus: float = 0.35,
    zero_diagonal: bool = True,
) -> pd.DataFrame:
    """Gaussian distance-decay weights, optionally boosted by shared borders.

    ``w_ij = exp(-(d_ij / h)^2) + border_bonus * 1{i,j share a border}``

    Rows are normalised to sum to one so that the resulting spatial feature is
    a weighted *average* of neighbour activity rather than a size-driven sum.
    """
    weights = np.exp(-((distances.to_numpy() / float(bandwidth_km)) ** 2))
    if shared_border is not None:
        weights = weights + border_bonus * shared_border.reindex(
            index=distances.index, columns=distances.columns
        ).fillna(0.0).to_numpy()
    if zero_diagonal:
        np.fill_diagonal(weights, 0.0)
    row_sums = weights.sum(axis=1, keepdims=True)
    row_sums[row_sums < 1e-12] = 1.0
    return pd.DataFrame(weights / row_sums, index=distances.index, columns=distances.columns)


def build_adjacency(countries: Mapping[str, CountrySpec]) -> pd.DataFrame:
    """Binary shared-border matrix from the ``neighbours`` lists in config."""
    iso = list(countries.keys())
    frame = pd.DataFrame(0.0, index=iso, columns=iso)
    for code, spec in countries.items():
        for neighbour in spec.neighbours:
            if neighbour in frame.columns:
                frame.loc[code, neighbour] = 1.0
                frame.loc[neighbour, code] = 1.0  # enforce symmetry
    np.fill_diagonal(frame.values, 0.0)
    return frame


def jitter_point(
    lat: float, lon: float, *, radius_km: float, rng: np.random.Generator
) -> tuple[float, float]:
    """Random point uniformly distributed within *radius_km* of a centroid.

    Used by the sample generator to place synthetic outbreak locations inside a
    country rather than stacking them all on the centroid.
    """
    r = radius_km * np.sqrt(rng.uniform(0.0, 1.0))
    theta = rng.uniform(0.0, 2.0 * np.pi)
    dlat = (r * np.cos(theta)) / 110.574
    dlon = (r * np.sin(theta)) / (111.320 * max(np.cos(np.radians(lat)), 0.2))
    return float(np.clip(lat + dlat, -89.0, 89.0)), float(((lon + dlon + 180.0) % 360.0) - 180.0)


def country_radius_km(area_km2: float, *, cap_km: float = 700.0) -> float:
    """Equivalent-circle radius of a country, capped for very large states."""
    if area_km2 <= 0:
        return 50.0
    return float(min(np.sqrt(area_km2 / np.pi), cap_km))


def centroid_frame(countries: Mapping[str, CountrySpec]) -> pd.DataFrame:
    """Tidy frame of country metadata used by maps and joins."""
    rows: list[dict[str, object]] = []
    for code, spec in countries.items():
        rows.append(
            {
                "country_iso3": code,
                "country_name": spec.name,
                "region": spec.region,
                "lat": spec.lat,
                "lon": spec.lon,
                "area_km2": spec.area_km2,
                "surveillance_capacity": spec.surveillance_capacity,
            }
        )
    return pd.DataFrame(rows)


def neighbour_list(countries: Mapping[str, CountrySpec], iso3: str) -> Sequence[str]:
    spec = countries.get(iso3)
    return () if spec is None else spec.neighbours
