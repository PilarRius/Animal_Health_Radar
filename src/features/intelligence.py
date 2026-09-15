"""Intelligence features: fusing noisy, overlapping, unverified signals.

Media and aggregator signals arrive earlier than official notifications, which
is their whole value, and they overlap heavily with each other, which is their
whole problem. Two design choices follow:

**Keep the sources separate, then add a fused summary.** The individual
anomaly signals stay in the feature matrix so the model can learn their
different reliabilities, and a single ``intel_fused_anomaly`` is added as a
reliability-weighted, redundancy-discounted composite for the dashboard and for
models that need one number.

**Discount redundancy explicitly.** The composite divides the weighted sum by
the effective number of independent voices rather than by the raw source count,
using the dependence matrix in :mod:`src.linkage.independence`. Four media
sources shouting about one wire story therefore do not produce four times the
signal of one.

The corroboration count is emitted as its own feature so the confidence layer
can use it downstream.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.linkage.independence import effective_independent_sources, get_dependence_model
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["build_intelligence_features", "INTELLIGENCE_ANOMALY_SIGNALS"]

_FAMILY = "intelligence"

#: Signals that behave like standardised anomalies and can be fused directly.
INTELLIGENCE_ANOMALY_SIGNALS: dict[str, str] = {
    "gdelt_abnormal_volume": "GDELT",
    "padiweb_abnormal_volume": "PADI-web",
    "beacon_abnormal_volume": "BEACON",
    "healthmap_abnormal_volume": "HealthMap",
    "eios_abnormal_volume": "EIOS",
}

#: Additional intelligence signals kept as-is (levels, shares, accelerations).
_PASSTHROUGH: tuple[str, ...] = (
    "gdelt_acceleration",
    "gdelt_source_diversity",
    "gdelt_baseline_ratio",
    "gdelt_tone_negativity",
    "padiweb_acceleration",
    "padiweb_event_rate",
    "padiweb_mean_relevance",
    "beacon_verified_signals",
    "beacon_verified_strength",
    "beacon_max_strength",
    "beacon_media_dependence",
    "healthmap_unique_alerts",
    "healthmap_duplicate_share",
    "promed_confidence_weighted",
    "promed_post_count",
    "eios_retained_items",
    "eios_mean_relevance",
)


def build_intelligence_features(signals: pd.DataFrame) -> pd.DataFrame:
    """Return long feature-store rows for the intelligence family."""
    if signals.empty:
        return pd.DataFrame()

    frame = signals.copy()
    frame["reference_week"] = pd.to_datetime(frame["reference_week"], errors="coerce")
    frame["available_from"] = pd.to_datetime(frame["available_from"], errors="coerce")
    frame = frame.loc[frame["reference_week"].notna() & frame["available_from"].notna()]

    wanted = set(INTELLIGENCE_ANOMALY_SIGNALS) | set(_PASSTHROUGH)
    kept = frame.loc[frame["signal_name"].isin(wanted)].copy()
    if kept.empty:
        LOGGER.warning("No recognised intelligence signals in the corpus.")
        return pd.DataFrame()

    base = kept.rename(columns={"signal_name": "feature"})[
        ["entity_key", "country_iso3", "disease", "reference_week",
         "feature", "value", "available_from", "source_name"]
    ].rename(columns={"source_name": "source"})
    base["family"] = _FAMILY

    fused = _fuse(kept)
    out = pd.concat([base, fused], ignore_index=True)
    LOGGER.info("Intelligence features: %s rows across %s features",
                len(out), out["feature"].nunique())
    return out.reset_index(drop=True)


def _fuse(signals: pd.DataFrame) -> pd.DataFrame:
    """Redundancy-discounted composite of the anomaly signals.

    .. math::

        \\text{fused} = \\frac{\\sum_i r_i z_i}{\\max(n_{\\text{eff}}, 1)}
            \\cdot \\frac{n_{\\text{eff}}}{n}

    The first factor averages the reliability-weighted anomalies; the second
    penalises the case where many nominally distinct sources are in fact one
    voice. A single independent source therefore scores higher than four
    mutually dependent ones with the same average anomaly.
    """
    anomalies = signals.loc[signals["signal_name"].isin(INTELLIGENCE_ANOMALY_SIGNALS)].copy()
    if anomalies.empty:
        return pd.DataFrame()

    model = get_dependence_model()
    anomalies["reliability"] = pd.to_numeric(
        anomalies.get("reliability", 0.5), errors="coerce"
    ).fillna(0.5)

    # Cache n_eff by the frozen set of contributing sources: there are only a
    # handful of distinct combinations across the whole panel.
    cache: dict[tuple[str, ...], float] = {}

    records: list[dict[str, object]] = []
    group_cols = ["entity_key", "country_iso3", "disease", "reference_week"]
    for keys, group in anomalies.groupby(group_cols, sort=False):
        sources = tuple(sorted(group["source_name"].astype(str).unique()))
        if sources not in cache:
            weights = [
                float(group.loc[group["source_name"] == s, "reliability"].max()) for s in sources
            ]
            cache[sources] = effective_independent_sources(list(sources), weights, model=model)
        n_eff = cache[sources]
        n_sources = max(len(sources), 1)

        weighted = float((group["reliability"] * group["value"]).sum())
        weight_total = float(group["reliability"].sum())
        mean_weighted = weighted / max(weight_total, 1e-9)
        fused_value = mean_weighted * (n_eff / n_sources)

        entity_key, country, disease, reference_week = keys
        available = group["available_from"].max()
        common = {
            "entity_key": entity_key,
            "country_iso3": country,
            "disease": disease,
            "reference_week": reference_week,
            "available_from": available,
            "family": _FAMILY,
            "source": "fusion",
        }
        records.append({**common, "feature": "intel_fused_anomaly", "value": fused_value})
        records.append({**common, "feature": "intel_effective_sources", "value": n_eff})
        records.append(
            {**common, "feature": "intel_max_anomaly", "value": float(group["value"].max())}
        )
        records.append(
            {
                **common,
                "feature": "intel_corroborating_sources",
                "value": float((group["value"] > 1.0).sum()),
            }
        )

    fused = pd.DataFrame(records)
    fused["value"] = pd.to_numeric(fused["value"], errors="coerce")
    return fused.loc[np.isfinite(fused["value"])]
