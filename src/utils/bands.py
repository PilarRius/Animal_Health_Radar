"""Banding of continuous scores into the operational labels used by the UI.

``config/thresholds.yaml`` expresses bands as ``{name: lower_bound}`` maps, for
example::

    confidence_bands:
      low: 0.00
      moderate: 0.40
      high: 0.68

The highest band whose lower bound is not above the value wins. If a value
falls below every bound (which can only happen when the lowest bound is above
zero) the lowest-named band is returned rather than ``None``, so a score always
carries a label and the UI never has to render an empty badge.

Keeping this in one function matters: banding appears in the nowcast (reporting
gap), the alert builder (alert level, confidence, priority) and the dashboard
legends, and three slightly different implementations of ">=" would be three
slightly different alert systems.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

__all__ = ["band_for", "band_edges", "band_index"]


def band_edges(bands: Mapping[str, float]) -> list[tuple[str, float]]:
    """Band definitions sorted by ascending lower bound."""
    return sorted(((str(name), float(bound)) for name, bound in bands.items()), key=lambda p: p[1])


def band_for(value: float | None, bands: Mapping[str, float], *, default: str = "unknown") -> str:
    """Name of the band containing *value*."""
    edges = band_edges(bands)
    if not edges:
        return default
    if value is None or not np.isfinite(float(value)):
        return default
    chosen = edges[0][0]
    for name, bound in edges:
        if float(value) >= bound:
            chosen = name
        else:
            break
    return chosen


def band_index(name: str, bands: Mapping[str, float]) -> int:
    """Ordinal position of a band name (0 = lowest). ``-1`` when unknown."""
    for index, (candidate, _) in enumerate(band_edges(bands)):
        if candidate == name:
            return index
    return -1
