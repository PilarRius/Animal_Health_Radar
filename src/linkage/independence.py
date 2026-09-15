"""Evidence independence: how many *voices* are really speaking?

Counting sources is not counting evidence. If GDELT, PADI-web, HealthMap and
ProMED all pick up the same wire story, and BEACON and EIOS then cluster those
articles, the naive tally is "six independent sources agree" when the truthful
statement is closer to "one story, six times".

This module quantifies that with the standard **effective sample size** of a
set of correlated observations:

.. math::

    n_{\\text{eff}} = \\frac{\\left(\\sum_i w_i\\right)^2}{w^{\\top} R\\, w}

where :math:`w_i` is the weight (source reliability) and :math:`R` the
source-dependence correlation matrix assembled from
``config/config.yaml: independence``. Perfectly independent sources give
:math:`n_{\\text{eff}} = n`; perfectly redundant ones give
:math:`n_{\\text{eff}} = 1`.

The result feeds two things: the ``evidence_independence`` field on every alert
and a hard gate in ``config/thresholds.yaml`` that prevents a CRITICAL alert
from resting on a single dependent cluster.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache

import numpy as np
import pandas as pd

from src.utils.config import get_config
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = [
    "DependenceModel",
    "get_dependence_model",
    "effective_independent_sources",
    "cluster_of",
]


class DependenceModel:
    """Source-dependence correlation matrix built from configuration."""

    def __init__(self, clusters: Mapping[str, dict], cross: Mapping[str, float]) -> None:
        self._cluster_of: dict[str, str] = {}
        self._within: dict[str, float] = {}
        for cluster_name, spec in clusters.items():
            self._within[cluster_name] = float(spec.get("within_cluster_correlation", 0.5))
            for member in spec.get("members", []):
                self._cluster_of[str(member)] = cluster_name
        self._cross = {str(k): float(v) for k, v in cross.items()}
        self._default_cross = float(self._cross.get("default", 0.05))

    # -- lookups ---------------------------------------------------------- #
    def cluster_of(self, source: str) -> str:
        return self._cluster_of.get(source, "unknown")

    def correlation(self, source_a: str, source_b: str) -> float:
        """Assumed correlation between two sources' assertions."""
        if source_a == source_b:
            return 1.0
        cluster_a, cluster_b = self.cluster_of(source_a), self.cluster_of(source_b)
        if cluster_a == cluster_b:
            return self._within.get(cluster_a, 0.5)
        key = "__".join(sorted([cluster_a, cluster_b]))
        return self._cross.get(key, self._default_cross)

    def matrix(self, sources: Sequence[str]) -> np.ndarray:
        n = len(sources)
        out = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self.correlation(sources[i], sources[j])
                out[i, j] = out[j, i] = rho
        return out

    def to_frame(self, sources: Sequence[str]) -> pd.DataFrame:
        """Full matrix as a labelled frame, shown on the provenance screen."""
        return pd.DataFrame(self.matrix(list(sources)), index=list(sources), columns=list(sources))

    @property
    def known_sources(self) -> list[str]:
        return sorted(self._cluster_of)


@lru_cache(maxsize=1)
def get_dependence_model() -> DependenceModel:
    """Load the dependence model from configuration (cached)."""
    config = get_config()
    return DependenceModel(
        clusters=config.get("independence.clusters", {}) or {},
        cross=config.get("independence.cross_cluster_correlation", {}) or {},
    )


def cluster_of(source: str) -> str:
    return get_dependence_model().cluster_of(source)


def effective_independent_sources(
    sources: Sequence[str],
    weights: Sequence[float] | None = None,
    *,
    model: DependenceModel | None = None,
) -> float:
    """Effective number of independent voices behind a set of sources.

    Parameters
    ----------
    sources:
        Source names, duplicates allowed (they are collapsed first, because the
        same source contributing twice is still one voice).
    weights:
        Per-source weight, typically the provenance reliability. Defaults to 1.

    Returns
    -------
    ``n_eff`` in ``[1, n]`` for a non-empty input, ``0.0`` for no evidence.
    """
    model = model or get_dependence_model()
    unique: dict[str, float] = {}
    if weights is None:
        weights = [1.0] * len(sources)
    for source, weight in zip(sources, weights, strict=True):
        name = str(source)
        # A source that speaks twice is still one voice: keep its largest weight.
        unique[name] = max(unique.get(name, 0.0), float(weight))
    if not unique:
        return 0.0

    names = list(unique)
    w = np.array([unique[name] for name in names], dtype=float)
    if w.sum() <= 0:
        return 0.0
    R = model.matrix(names)
    denominator = float(w @ R @ w)
    if denominator <= 0:
        return 1.0
    n_eff = float((w.sum() ** 2) / denominator)
    return float(np.clip(n_eff, 1.0, float(len(names))))


def independence_report(sources: Sequence[str], weights: Sequence[float] | None = None) -> dict:
    """Detailed breakdown used in the 'why this alert' panel."""
    model = get_dependence_model()
    unique = sorted(set(str(s) for s in sources))
    by_cluster: dict[str, list[str]] = {}
    for source in unique:
        by_cluster.setdefault(model.cluster_of(source), []).append(source)
    n_eff = effective_independent_sources(sources, weights, model=model)
    return {
        "n_sources": len(unique),
        "n_clusters": len(by_cluster),
        "effective_independent_sources": round(n_eff, 3),
        "redundancy": round(1.0 - n_eff / max(len(unique), 1), 3),
        "by_cluster": {k: sorted(v) for k, v in sorted(by_cluster.items())},
    }
