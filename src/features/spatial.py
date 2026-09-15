"""Spatial risk features: what the neighbourhood is doing.

Transboundary animal diseases do not respect the country polygons that WAHIS
reports in. ASF has advanced through the European wild boar population as a
front; HPAI arrives along flyways that cross a dozen jurisdictions in a season.
A country with no reports of its own but three neighbours in active outbreak is
in a very different position from one surrounded by quiet.

The neighbourhood is defined by a Gaussian distance-decay kernel over country
centroids, boosted for shared land borders, and row-normalised so the feature
is a weighted *average* of neighbour activity rather than something that grows
with the number of neighbours.

Crucially, the neighbour activity is read from the **same vintage** as the
country's own series: what the neighbours had actually published by ``as_of``,
not what we now know they were experiencing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.temporal import OfficialHistory
from src.utils.config import load_countries
from src.utils.dates import DateLike, ensure_date, iso_week_start
from src.utils.geo import build_adjacency, decay_kernel, distance_matrix
from src.utils.logging_utils import get_logger
from src.utils.stats import safe_log

LOGGER = get_logger(__name__)

__all__ = ["SpatialContext", "spatial_features", "SPATIAL_FEATURES"]

SPATIAL_FEATURES: tuple[str, ...] = (
    "spa_neighbour_activity_4w",
    "spa_neighbour_activity_13w",
    "spa_neighbour_growth",
    "spa_neighbour_active_share",
    "spa_nearest_active_km",
    "spa_border_pressure",
)


class SpatialContext:
    """Pre-computed neighbourhood weights for the country panel."""

    def __init__(self, bandwidth_km: float = 900.0, border_bonus: float = 0.35) -> None:
        countries = load_countries()
        self.iso3: list[str] = list(countries)
        self.distances = distance_matrix(countries)
        self.adjacency = build_adjacency(countries)
        self.weights = decay_kernel(
            self.distances,
            bandwidth_km=bandwidth_km,
            shared_border=self.adjacency,
            border_bonus=border_bonus,
        )
        self._w = self.weights.to_numpy()
        self._d = self.distances.to_numpy()
        self._adj = self.adjacency.to_numpy()
        self._position = {iso: i for i, iso in enumerate(self.iso3)}

    def position(self, iso3: str) -> int | None:
        return self._position.get(iso3)


def spatial_features(
    history: OfficialHistory,
    as_of: DateLike,
    *,
    context: SpatialContext | None = None,
) -> pd.DataFrame:
    """Neighbourhood activity features, computed per disease.

    Spillover is disease-specific: Polish ASF tells you nothing about French
    HPAI. The kernel is therefore applied within each disease's country vector
    separately.
    """
    context = context or SpatialContext()
    counts = history.counts_as_of(as_of)
    as_of_date = ensure_date(as_of)
    w_now = history.week_position(iso_week_start(as_of_date))
    visible = counts[:, : w_now + 1]

    # Aggregate each entity's own recent activity
    recent_4 = visible[:, -4:].sum(axis=1) if visible.shape[1] else np.zeros(visible.shape[0])
    recent_13 = visible[:, -13:].sum(axis=1) if visible.shape[1] else np.zeros(visible.shape[0])
    previous_4 = (
        visible[:, -8:-4].sum(axis=1) if visible.shape[1] >= 8 else np.zeros(visible.shape[0])
    )

    own_4 = pd.Series(recent_4, index=history.entities)
    own_13 = pd.Series(recent_13, index=history.entities)
    own_prev_4 = pd.Series(previous_4, index=history.entities)

    rows: list[dict[str, object]] = []
    diseases = sorted({history.entity_disease[key] for key in history.entities})

    for disease in diseases:
        entities = [key for key in history.entities if history.entity_disease[key] == disease]
        positions = [context.position(history.entity_country[key]) for key in entities]
        valid = [i for i, pos in enumerate(positions) if pos is not None]
        if not valid:
            continue
        idx = np.array([positions[i] for i in valid], dtype=int)
        keys = [entities[i] for i in valid]

        activity_4 = own_4.loc[keys].to_numpy(dtype=float)
        activity_13 = own_13.loc[keys].to_numpy(dtype=float)
        activity_prev_4 = own_prev_4.loc[keys].to_numpy(dtype=float)

        sub_w = context._w[np.ix_(idx, idx)]
        # Re-normalise: the panel is a subset of the world, so weights must sum to 1
        row_sums = sub_w.sum(axis=1, keepdims=True)
        row_sums[row_sums < 1e-12] = 1.0
        sub_w = sub_w / row_sums

        neighbour_4 = sub_w @ safe_log(activity_4)
        neighbour_13 = sub_w @ safe_log(activity_13)
        neighbour_prev_4 = sub_w @ safe_log(activity_prev_4)
        active = (activity_4 > 0).astype(float)
        neighbour_active_share = sub_w @ active

        sub_d = context._d[np.ix_(idx, idx)]
        sub_adj = context._adj[np.ix_(idx, idx)]
        distance_to_active = np.where(active[None, :] > 0, sub_d, np.inf)
        np.fill_diagonal(distance_to_active, np.inf)
        nearest_active = distance_to_active.min(axis=1)
        nearest_active = np.where(np.isfinite(nearest_active), nearest_active, 6000.0)

        border_pressure = (sub_adj * active[None, :]).sum(axis=1)

        for j, key in enumerate(keys):
            rows.append(
                {
                    "entity_key": key,
                    "spa_neighbour_activity_4w": float(neighbour_4[j]),
                    "spa_neighbour_activity_13w": float(neighbour_13[j]),
                    "spa_neighbour_growth": float(neighbour_4[j] - neighbour_prev_4[j]),
                    "spa_neighbour_active_share": float(neighbour_active_share[j]),
                    "spa_nearest_active_km": float(nearest_active[j]),
                    "spa_border_pressure": float(border_pressure[j]),
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame({"entity_key": history.entities})
        for name in SPATIAL_FEATURES:
            frame[name] = 0.0
    frame["as_of"] = pd.Timestamp(as_of_date)
    return frame
