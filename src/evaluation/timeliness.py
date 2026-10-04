"""Lead-time evaluation: how early did the model cross investigation before WAHIS?

Respects as-of semantics: for each first official notification week, look at
historical predictions with ``as_of < notification`` and find the first date
the investigation threshold was crossed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.utils.config import get_config, load_thresholds
from src.utils.logging_utils import get_logger

LOGGER = get_logger(__name__)

__all__ = ["lead_time_report", "first_official_notifications"]


def first_official_notifications(canonical_events: pd.DataFrame) -> pd.DataFrame:
    """First public INFUR notification per country × disease episode window.

    Uses the earliest ``available_from`` per entity, then subsequent
    notifications after a quiet gap (>= 8 weeks) as new episodes.
    """
    if canonical_events.empty:
        return pd.DataFrame()
    frame = canonical_events.copy()
    frame["available_from"] = pd.to_datetime(frame["available_from"], errors="coerce")
    frame["reference_date"] = pd.to_datetime(
        frame.get("reference_date", frame["available_from"]), errors="coerce"
    )
    frame = frame.dropna(subset=["available_from", "country_iso3", "disease"])
    frame = frame.sort_values(["country_iso3", "disease", "available_from"])

    quiet = pd.Timedelta(weeks=int(get_config().get("early_warning.quiet_period_weeks", 8)))
    rows: list[dict[str, Any]] = []
    for (iso, disease), block in frame.groupby(["country_iso3", "disease"], sort=False):
        prev = None
        for _, row in block.iterrows():
            ts = row["available_from"]
            if prev is None or (ts - prev) >= quiet:
                rows.append(
                    {
                        "country_iso3": iso,
                        "disease": disease,
                        "entity_key": f"{iso}|{disease}",
                        "notification_date": ts.date() if hasattr(ts, "date") else ts,
                        "reference_date": (
                            row["reference_date"].date()
                            if pd.notna(row["reference_date"])
                            else None
                        ),
                        "outbreak_id": row.get("event_id") or row.get("canonical_event_id"),
                    }
                )
                prev = ts
            else:
                prev = ts
    return pd.DataFrame(rows)


def lead_time_report(
    predictions: pd.DataFrame,
    canonical_events: pd.DataFrame,
    *,
    probability_col: str = "early_warning_probability",
    as_of_col: str = "as_of_date",
) -> dict[str, Any]:
    """Compute lead-time distribution vs first official notifications."""
    thresholds = load_thresholds()
    # Prefer ALERT (targeted investigation) then WATCH; concept note ~0.60.
    investigate = 0.40
    levels = {str(b.get("level", "")).lower(): float(b.get("min_probability", 0))
              for b in thresholds.get("alert_levels", [])}
    if "alert" in levels:
        investigate = levels["alert"]
    elif "watch" in levels:
        investigate = levels["watch"]

    episodes = first_official_notifications(canonical_events)
    if episodes.empty or predictions.empty:
        return {"n_episodes": 0, "note": "No episodes or predictions to score."}

    pred = predictions.copy()
    pred[as_of_col] = pd.to_datetime(pred[as_of_col]).dt.date
    pred["entity_key"] = pred.get("entity_key")
    if pred["entity_key"].isna().all():
        pred["entity_key"] = pred["country"].astype(str) + "|" + pred["disease"].astype(str)

    lead_days: list[float] = []
    detected = 0
    case_rows: list[dict[str, Any]] = []

    for _, ep in episodes.iterrows():
        entity = ep["entity_key"]
        notify = ep["notification_date"]
        hist = pred.loc[
            (pred["entity_key"] == entity) & (pred[as_of_col] < notify)
        ].sort_values(as_of_col)
        if hist.empty:
            case_rows.append(
                {
                    "entity_key": entity,
                    "notification_date": str(notify),
                    "detected": False,
                    "lead_days": None,
                    "first_cross_as_of": None,
                }
            )
            continue
        crossed = hist.loc[hist[probability_col] >= investigate]
        if crossed.empty:
            case_rows.append(
                {
                    "entity_key": entity,
                    "notification_date": str(notify),
                    "detected": False,
                    "lead_days": None,
                    "first_cross_as_of": None,
                    "max_prob_before": float(hist[probability_col].max()),
                }
            )
            continue
        first = crossed.iloc[0]
        lead = (pd.Timestamp(notify) - pd.Timestamp(first[as_of_col])).days
        lead_days.append(float(lead))
        detected += 1
        case_rows.append(
            {
                "entity_key": entity,
                "notification_date": str(notify),
                "detected": True,
                "lead_days": lead,
                "first_cross_as_of": str(first[as_of_col]),
                "prob_at_cross": float(first[probability_col]),
            }
        )

    arr = np.asarray(lead_days, dtype=float)
    summary = {
        "threshold_investigate": investigate,
        "n_episodes": int(len(episodes)),
        "n_detected_before_notification": int(detected),
        "detection_rate": float(detected / len(episodes)) if len(episodes) else 0.0,
        "lead_days_median": float(np.median(arr)) if arr.size else None,
        "lead_days_mean": float(np.mean(arr)) if arr.size else None,
        "lead_days_p25": float(np.quantile(arr, 0.25)) if arr.size else None,
        "lead_days_p75": float(np.quantile(arr, 0.75)) if arr.size else None,
        "lead_days_positive_share": float(np.mean(arr > 0)) if arr.size else None,
        "cases": case_rows[:50],  # keep report-sized sample
        "caveat": (
            "Lead time uses model early-warning probability vs first INFUR "
            "publication after a quiet gap. Enrichment signals may be synthetic "
            "in pilot mode; official observation is real INFUR."
        ),
    }
    LOGGER.info(
        "Lead time: detected %s/%s episodes before notification; median lead %s d",
        detected,
        len(episodes),
        summary["lead_days_median"],
    )
    return summary
