"""Entity resolution, de-duplication and evidence-independence control."""

from src.linkage.dedup import build_reporting_triangle, deduplicate_official, evidence_sets
from src.linkage.entity_resolution import LinkageResult, UnionFind, resolve_entities
from src.linkage.independence import (
    DependenceModel,
    cluster_of,
    effective_independent_sources,
    get_dependence_model,
    independence_report,
)

__all__ = [
    "DependenceModel",
    "LinkageResult",
    "UnionFind",
    "build_reporting_triangle",
    "cluster_of",
    "deduplicate_official",
    "effective_independent_sources",
    "evidence_sets",
    "get_dependence_model",
    "independence_report",
    "resolve_entities",
]
