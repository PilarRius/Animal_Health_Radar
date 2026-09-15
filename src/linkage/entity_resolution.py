"""Cross-source entity resolution.

The same outbreak is frequently described by WAHIS, echoed by EMPRES-i, covered
by three news outlets and clustered by two aggregators. Counting those as six
events would inflate the burden; counting them as six independent pieces of
evidence would inflate the confidence. Both errors are avoided by resolving
them to one **canonical event** first.

Matching strategy
-----------------
1. **Explicit references win.** When a record names its upstream source (as
   EMPRES-i does), the link is taken as given. Deterministic links are always
   preferred over probabilistic ones.
2. **Blocked temporal-spatial matching** for the rest. Records are blocked on
   (disease, country); within a block they are sorted by reference date and
   only compared inside a sliding time window, which keeps the cost linear
   instead of quadratic.
3. **Union-find** merges the pairwise decisions into clusters transitively.

Every merge decision is recorded with its rule and score, so the linkage is
auditable rather than a black box.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.utils.geo import haversine_km
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["LinkageResult", "resolve_entities", "UnionFind"]


class UnionFind:
    """Disjoint-set forest with path compression and union by size."""

    def __init__(self, keys: list[str]) -> None:
        self._parent: dict[str, str] = {key: key for key in keys}
        self._size: dict[str, int] = {key: 1 for key in keys}

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:          # path compression
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        return True

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key in self._parent:
            out.setdefault(self.find(key), []).append(key)
        return out


@dataclass
class LinkageResult:
    """Outcome of entity resolution."""

    events: pd.DataFrame           # input events + canonical_event_id
    clusters: pd.DataFrame         # one row per canonical event
    decisions: pd.DataFrame        # audit trail of every merge

    @property
    def n_clusters(self) -> int:
        return len(self.clusters)

    def summary(self) -> dict[str, float]:
        return {
            "n_events": float(len(self.events)),
            "n_canonical_events": float(self.n_clusters),
            "duplication_ratio": float(len(self.events) / max(self.n_clusters, 1)),
            "n_merge_decisions": float(len(self.decisions)),
        }


def resolve_entities(
    events: pd.DataFrame,
    *,
    time_window_days: int = 3,
    distance_km: float = 10.0,
    require_same_admin1: bool = False,
    min_score: float = 0.55,
) -> LinkageResult:
    """Assign a ``canonical_event_id`` to every event record.

    Thresholds are deliberately tight. Union-find merges transitively, so a
    generous matcher does not merely make a few extra links: it chains distinct
    foci together through intermediate records and silently collapses an
    epidemic into a handful of "events". Under-merging costs a little duplicate
    counting that the independence layer already discounts; over-merging
    destroys the burden estimate outright. Only the best-scoring candidate per
    record is considered, which further limits chaining.

    Parameters
    ----------
    time_window_days:
        Maximum separation of reference dates for two records to be candidates.
    distance_km:
        Maximum centroid separation when both records are geo-located. Records
        without coordinates fall back to the administrative unit.
    require_same_admin1:
        Stricter matching for sources with reliable administrative coding.
    min_score:
        Minimum combined temporal-spatial similarity required to merge.
    """
    if events.empty:
        empty = pd.DataFrame(columns=["canonical_event_id"])
        return LinkageResult(events=events, clusters=empty, decisions=empty)

    frame = events.copy().reset_index(drop=True)
    # Identifiers must be unique before union-find. Always namespace by source;
    # a collision between two sources' id spaces would merge unrelated records.
    frame["_key"] = frame["source_name"].astype(str) + "::" + frame["event_id"].astype(str)
    duplicated = int(frame["_key"].duplicated().sum())
    if duplicated:
        LOGGER.warning(
            "%s record(s) share an event_id within their own source. Linkage cannot "
            "distinguish them; suffixing to keep them separate and flagging as a data "
            "quality issue.", duplicated,
        )
        frame["_key"] = frame["_key"] + "#" + frame.groupby("_key").cumcount().astype(str)

    union = UnionFind(frame["_key"].tolist())
    decisions: list[dict[str, object]] = []

    # Source membership per cluster. Two clusters that each already contain a
    # record from the same source describe two distinct foci that source chose
    # to report separately, so they must never be merged probabilistically.
    # Without this, A(WAHIS) links to B'(EMPRES-i), B' is already tied to
    # B(WAHIS), and two genuine outbreaks silently collapse into one.
    cluster_sources: dict[str, set[str]] = {
        key: {str(source)}
        for key, source in zip(frame["_key"], frame["source_name"], strict=True)
    }

    def _merge(a: str, b: str, *, enforce_disjoint: bool) -> bool:
        root_a, root_b = union.find(a), union.find(b)
        if root_a == root_b:
            return False
        if enforce_disjoint and (cluster_sources[root_a] & cluster_sources[root_b]):
            return False
        if not union.union(a, b):
            return False
        new_root = union.find(a)
        merged = cluster_sources.pop(root_a, set()) | cluster_sources.pop(root_b, set())
        cluster_sources[new_root] = merged
        return True

    # -- rule 1: explicit upstream references ----------------------------- #
    # An upstream reference names a record in another source's id space, so the
    # lookup is on the bare event_id. Ambiguous ids are excluded: following a
    # reference to the wrong record is worse than not following it.
    counts = frame["event_id"].astype(str).value_counts()
    unambiguous = set(counts.loc[counts == 1].index)
    lookup_by_id: dict[str, str] = {
        str(event_id): key
        for event_id, key in zip(frame["event_id"].astype(str), frame["_key"], strict=True)
        if str(event_id) in unambiguous
    }

    if "source_event_id" in frame.columns:
        for key, upstream in zip(frame["_key"], frame["source_event_id"], strict=True):
            if upstream is None or (isinstance(upstream, float) and np.isnan(upstream)):
                continue
            target = lookup_by_id.get(str(upstream))
            if target and target != key and _merge(key, target, enforce_disjoint=False):
                decisions.append(
                    {"rule": "explicit_reference", "a": key, "b": target, "score": 1.0,
                     "detail": f"source_event_id -> {upstream}"}
                )

    # -- rule 2: blocked temporal-spatial matching ------------------------- #
    frame["_ref"] = pd.to_datetime(frame["reference_date"], errors="coerce")
    frame = frame.sort_values(["disease", "country_iso3", "_ref"], kind="mergesort")

    for (disease, country), block in frame.groupby(["disease", "country_iso3"], sort=False):
        if len(block) < 2:
            continue
        keys = block["_key"].to_numpy()
        refs = block["_ref"].to_numpy()
        lats = pd.to_numeric(block.get("latitude"), errors="coerce").to_numpy(dtype=float)
        lons = pd.to_numeric(block.get("longitude"), errors="coerce").to_numpy(dtype=float)
        admin = block.get("admin1", pd.Series([None] * len(block))).astype(str).to_numpy()
        sources = block["source_name"].astype(str).to_numpy()
        window = np.timedelta64(int(time_window_days), "D")

        j_start = 0
        for i in range(len(block)):
            while j_start < i and (refs[i] - refs[j_start]) > window:
                j_start += 1

            best: tuple[float, int, float, int] | None = None
            for j in range(j_start, i):
                if sources[i] == sources[j]:
                    # Two foci reported separately by the SAME source are two
                    # real foci, not a duplicate. Never merge within a source.
                    continue
                if require_same_admin1 and admin[i] != admin[j]:
                    continue
                if np.isfinite(lats[i]) and np.isfinite(lats[j]):
                    separation = float(haversine_km(lats[i], lons[i], lats[j], lons[j]))
                    if separation > distance_km:
                        continue
                elif admin[i] != admin[j]:
                    continue
                else:
                    separation = float("nan")

                days_apart = abs(int((refs[i] - refs[j]) / np.timedelta64(1, "D")))
                score = float(
                    0.5 * (1.0 - days_apart / max(time_window_days, 1))
                    + 0.5 * (1.0 - (separation / distance_km if np.isfinite(separation) else 0.5))
                )
                if score >= min_score and (best is None or score > best[0]):
                    best = (score, j, separation, days_apart)

            if best is None:
                continue
            score, j, separation, days_apart = best
            if _merge(keys[i], keys[j], enforce_disjoint=True):
                detail = (
                    f"{disease}/{country} {days_apart}d, {separation:.1f}km"
                    if np.isfinite(separation)
                    else f"{disease}/{country} {days_apart}d, same admin1"
                )
                decisions.append(
                    {"rule": "temporal_spatial_best_match", "a": keys[i], "b": keys[j],
                     "score": round(score, 4), "detail": detail}
                )

    # -- assemble ---------------------------------------------------------- #
    frame["canonical_event_id"] = [union.find(key) for key in frame["_key"]]
    # Human-friendlier cluster ids
    ordered = {root: f"CE-{index:07d}" for index, root in enumerate(
        sorted(frame["canonical_event_id"].unique()), start=1
    )}
    frame["canonical_event_id"] = frame["canonical_event_id"].map(ordered)

    clusters = _build_clusters(frame)
    decision_frame = pd.DataFrame(decisions)
    LOGGER.info(
        "Entity resolution: %s records -> %s canonical events (%.2f records per event)",
        len(frame), len(clusters), len(frame) / max(len(clusters), 1),
    )
    return LinkageResult(
        events=frame.drop(columns=["_key", "_ref"]).reset_index(drop=True),
        clusters=clusters,
        decisions=decision_frame,
    )


def _build_clusters(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per canonical event with the contributing sources.

    Written as vectorised group-bys rather than ``groupby.apply``: there are
    thousands of clusters and a per-group Python callback dominates the whole
    ingestion stage.
    """
    work = frame.copy()
    work["_is_primary"] = (work["source_type"] == "official") & (
        ~work.get("is_downstream_of_official", pd.Series(False, index=work.index)).astype(bool)
    )
    for column in ("outbreaks", "cases", "deaths", "latitude", "longitude"):
        if column not in work.columns:
            work[column] = np.nan
    work["outbreaks"] = pd.to_numeric(work["outbreaks"], errors="coerce").fillna(1.0)

    grouped = work.groupby("canonical_event_id", sort=True)
    clusters = grouped.agg(
        entity_key=("entity_key", "first"),
        country_iso3=("country_iso3", "first"),
        disease=("disease", "first"),
        n_records=("event_id", "size"),
        n_sources=("source_name", "nunique"),
        first_available_from=("available_from", "min"),
        has_official=("_is_primary", "any"),
    ).reset_index()

    sources = (
        work.groupby("canonical_event_id")["source_name"]
        .agg(lambda s: ";".join(sorted(set(s))))
        .rename("sources")
    )
    clusters = clusters.merge(sources, on="canonical_event_id", how="left")
    if "evidence_cluster" in work.columns:
        present = (
            work.groupby("canonical_event_id")["evidence_cluster"]
            .agg(lambda s: ";".join(sorted(set(s.dropna()))))
            .rename("clusters_present")
        )
        clusters = clusters.merge(present, on="canonical_event_id", how="left")
    else:
        clusters["clusters_present"] = ""

    # Anchor: the primary official record where one exists, else any record.
    anchor_source = work.loc[work["_is_primary"]] if work["_is_primary"].any() else work
    anchor = anchor_source.groupby("canonical_event_id").agg(
        reference_date=("reference_date", "min"),
        official_available_from=("available_from", "min"),
        outbreaks=("outbreaks", "max"),
        cases=("cases", "max"),
        deaths=("deaths", "max"),
        latitude=("latitude", "mean"),
        longitude=("longitude", "mean"),
    ).reset_index()
    clusters = clusters.merge(anchor, on="canonical_event_id", how="left")

    fallback = work.groupby("canonical_event_id")["reference_date"].min().rename("_fallback_ref")
    clusters = clusters.merge(fallback, on="canonical_event_id", how="left")
    clusters["reference_date"] = clusters["reference_date"].fillna(clusters["_fallback_ref"])
    clusters = clusters.drop(columns=["_fallback_ref"])
    clusters["outbreaks"] = clusters["outbreaks"].fillna(1.0)

    clusters["intelligence_lead_days"] = (
        pd.to_datetime(clusters["official_available_from"])
        - pd.to_datetime(clusters["first_available_from"])
    ).dt.days
    return clusters
