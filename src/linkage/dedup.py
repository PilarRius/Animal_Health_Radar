"""De-duplication and the official burden series.

Once events are resolved into canonical clusters, two different quantities are
needed and must not be confused:

**Official burden** -- how many outbreaks are officially on the record. Built
from primary official records only. EMPRES-i re-publications are excluded, or
the same outbreak would be counted twice.

**Evidence set** -- which sources said something about this cluster, and when.
Here the EMPRES-i record *is* kept, because its publication date can precede
the WAHIS dissemination and therefore moves the availability date earlier.

The reporting triangle produced at the bottom is the object the nowcast
consumes: counts indexed by *when it happened* and *when it became knowable*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.linkage.independence import cluster_of, effective_independent_sources
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "deduplicate_official",
    "build_reporting_triangle",
    "evidence_sets",
]


def deduplicate_official(linked_events: pd.DataFrame) -> pd.DataFrame:
    """One row per canonical event carrying the official burden.

    Selection rule inside a cluster:

    1. prefer a primary official record (``source_type == 'official'``);
    2. among those, prefer the one that became available earliest -- that is
       the moment the world actually learnt about it;
    3. if no official record exists, the cluster is intelligence-only and is
       retained with ``has_official = False`` and zero official burden.
    """
    if linked_events.empty:
        return linked_events

    frame = linked_events.copy()
    frame["_is_primary"] = (frame["source_type"] == "official") & (
        ~frame.get("is_downstream_of_official", pd.Series(False, index=frame.index)).astype(bool)
    )
    frame = frame.sort_values(
        ["canonical_event_id", "_is_primary", "available_from"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    chosen = frame.groupby("canonical_event_id", as_index=False, sort=False).head(1).copy()

    # Attach cluster-level evidence metadata
    meta = frame.groupby("canonical_event_id").agg(
        n_records_in_cluster=("event_id", "size"),
        n_sources_in_cluster=("source_name", "nunique"),
        cluster_sources=("source_name", lambda s: ";".join(sorted(set(s)))),
        earliest_any_signal=("available_from", "min"),
        has_official=("_is_primary", "any"),
    )
    chosen = chosen.merge(meta, on="canonical_event_id", how="left")
    chosen["official_burden"] = np.where(chosen["has_official"], chosen["outbreaks"].fillna(1.0), 0.0)
    chosen["evidence_lead_days"] = (
        pd.to_datetime(chosen["available_from"]) - pd.to_datetime(chosen["earliest_any_signal"])
    ).dt.days.clip(lower=0)

    LOGGER.info(
        "De-duplication: %s linked records -> %s canonical events (%s with an official record)",
        len(frame), len(chosen), int(chosen["has_official"].sum()),
    )
    return chosen.drop(columns=["_is_primary"]).reset_index(drop=True)


def build_reporting_triangle(
    official_events: pd.DataFrame,
    *,
    value_col: str = "official_burden",
) -> pd.DataFrame:
    """Counts indexed by reference week and availability week.

    This is the classical nowcasting *reporting triangle*: row = week the event
    occurred, column = week it became observable. Summing across availability
    weeks ``<= as_of`` reproduces exactly what was visible at that moment, and
    the missing mass below the diagonal is what the nowcast must estimate.
    """
    if official_events.empty:
        return pd.DataFrame(
            columns=["entity_key", "country_iso3", "disease", "reference_week",
                     "available_week", "count", "delay_weeks"]
        )

    frame = official_events.loc[official_events.get("has_official", True) == True].copy()  # noqa: E712
    frame["reference_week"] = _week_start(frame["reference_date"])
    frame["available_week"] = _week_start(frame["available_from"])
    frame["_value"] = pd.to_numeric(frame[value_col], errors="coerce").fillna(1.0)

    triangle = frame.groupby(
        ["entity_key", "country_iso3", "disease", "reference_week", "available_week"],
        as_index=False,
    )["_value"].sum().rename(columns={"_value": "count"})

    triangle["delay_weeks"] = (
        (triangle["available_week"] - triangle["reference_week"]).dt.days // 7
    ).clip(lower=0)
    return triangle.sort_values(["entity_key", "reference_week", "available_week"]).reset_index(
        drop=True
    )


def evidence_sets(linked_events: pd.DataFrame) -> pd.DataFrame:
    """Per canonical event: which sources, which clusters, how independent."""
    if linked_events.empty:
        return pd.DataFrame(
            columns=["canonical_event_id", "sources", "n_sources",
                     "evidence_independence", "clusters"]
        )

    frame = linked_events.copy()
    frame["source_name"] = frame["source_name"].astype(str)
    if "reliability" not in frame.columns:
        frame["reliability"] = 0.5
    frame["reliability"] = pd.to_numeric(frame["reliability"], errors="coerce").fillna(0.5)

    # One reliability per source (the same source always carries the same weight)
    source_weight = frame.groupby("source_name")["reliability"].max().to_dict()

    grouped = frame.groupby("canonical_event_id", sort=True)
    out = grouped.agg(
        entity_key=("entity_key", "first"),
        reference_date=("reference_date", "min"),
        sources=("source_name", lambda s: ";".join(sorted(set(s)))),
    ).reset_index()
    out["n_sources"] = out["sources"].str.count(";") + 1

    # There are only a few dozen distinct source combinations across thousands
    # of clusters, so the expensive n_eff computation is memoised on the combo.
    cache: dict[str, tuple[float, str]] = {}

    def _resolve(combo: str) -> tuple[float, str]:
        if combo not in cache:
            names = combo.split(";")
            weights = [source_weight.get(name, 0.5) for name in names]
            cache[combo] = (
                round(effective_independent_sources(names, weights), 4),
                ";".join(sorted({cluster_of(name) for name in names})),
            )
        return cache[combo]

    resolved = out["sources"].map(_resolve)
    out["evidence_independence"] = [value[0] for value in resolved]
    out["clusters"] = [value[1] for value in resolved]
    return out


def _week_start(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize()
