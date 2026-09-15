"""Load precomputed parquet artefacts for the Shiny app."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.utils.config import get_config, load_countries, load_diseases
from src.utils.io import read_json, read_parquet


@dataclass
class AppData:
    predictions: pd.DataFrame
    alerts: pd.DataFrame
    explanations: dict
    nowcast_latest: pd.DataFrame | None
    countries: dict
    diseases: dict
    data_mode: str
    as_of_dates: list[str]
    project_root: Path
    provenance: pd.DataFrame = field(default_factory=pd.DataFrame)
    signals: pd.DataFrame = field(default_factory=pd.DataFrame)
    observed_final: pd.DataFrame = field(default_factory=pd.DataFrame)

    @classmethod
    def load(cls, project_root: Path) -> AppData:
        config = get_config()
        processed = config.path("data_processed")
        interim = config.path("data_interim")

        predictions = read_parquet(processed / "predictions.parquet")
        alerts = read_parquet(processed / "alerts.parquet")
        explanations = {}
        exp_path = processed / "explanations.json"
        if exp_path.exists():
            explanations = read_json(exp_path)

        nowcast = None
        nc_path = processed / "nowcast_latest.parquet"
        if nc_path.exists():
            nowcast = read_parquet(nc_path)

        provenance = pd.DataFrame()
        prov_path = interim / "provenance.parquet"
        if prov_path.exists():
            provenance = read_parquet(prov_path)

        signals = pd.DataFrame()
        sig_path = interim / "signals.parquet"
        if sig_path.exists():
            # Keep a slim intelligence subset for timelines
            signals = read_parquet(sig_path)
            if "signal_family" in signals.columns:
                signals = signals.loc[
                    signals["signal_family"].astype(str).str.contains("intel|media|aggreg", case=False, na=False)
                    | signals.get("source_type", pd.Series(dtype=str)).astype(str).isin(
                        ["media", "aggregator", "official"]
                    )
                ]
            keep = [c for c in (
                "entity_key", "country_iso3", "disease", "available_from", "reference_date",
                "signal_name", "signal_family", "value", "source_name", "source_type",
                "evidence_cluster", "provenance_id",
            ) if c in signals.columns]
            signals = signals[keep] if keep else signals

        observed_final = pd.DataFrame()
        obs_path = processed / "observed_final_series.parquet"
        if obs_path.exists():
            observed_final = read_parquet(obs_path)

        as_of_dates = sorted(predictions["as_of_date"].astype(str).unique().tolist())
        return cls(
            predictions=predictions,
            alerts=alerts,
            explanations=explanations,
            nowcast_latest=nowcast,
            countries=load_countries(),
            diseases=load_diseases(),
            data_mode=config.data_mode,
            as_of_dates=as_of_dates,
            project_root=project_root,
            provenance=provenance,
            signals=signals,
            observed_final=observed_final,
        )

    def predictions_as_of(self, as_of: str, disease: str) -> pd.DataFrame:
        frame = self.predictions.loc[self.predictions["as_of_date"].astype(str) == str(as_of)].copy()
        if disease and disease != "ALL":
            frame = frame.loc[frame["disease"] == disease]
        return frame

    def entity_series(self, entity_key: str) -> pd.DataFrame:
        return (
            self.predictions.loc[self.predictions["entity_key"] == entity_key]
            .sort_values("as_of_date")
            .copy()
        )

    def explanation_for(self, alert_id: str) -> dict | None:
        for item in self.explanations.get("explanations", []):
            if item.get("alert_id") == alert_id:
                return item.get("explanation")
        return None

    def evidence_timeline(self, entity_key: str, as_of: str, *, lookback_days: int = 60) -> pd.DataFrame:
        """Build a simple evidence timeline knowable at as_of."""
        as_of_ts = pd.Timestamp(as_of)
        start = as_of_ts - pd.Timedelta(days=lookback_days)
        rows: list[dict] = []

        series = self.entity_series(entity_key)
        series = series.loc[pd.to_datetime(series["as_of_date"]) <= as_of_ts]
        # Alert crossings
        for level, label in (("WATCH", "Model crosses WATCH"), ("ALERT", "Model crosses ALERT"), ("CRITICAL", "Model crosses CRITICAL")):
            hit = series.loc[series["alert_level"] == level]
            if not hit.empty:
                first = hit.iloc[0]
                rows.append({
                    "timestamp": str(first["as_of_date"])[:10],
                    "event": label,
                    "detail": f"EW p={float(first['early_warning_probability']):.0%}",
                    "family": "model",
                })

        # Intelligence / environmental signals from interim (if present)
        if not self.signals.empty and "entity_key" in self.signals.columns:
            sig = self.signals.loc[self.signals["entity_key"] == entity_key].copy()
            if "available_from" in sig.columns:
                sig["available_from"] = pd.to_datetime(sig["available_from"], errors="coerce")
                sig = sig.loc[(sig["available_from"] >= start) & (sig["available_from"] <= as_of_ts)]
                sig = sig.sort_values("available_from").tail(12)
                for _, r in sig.iterrows():
                    rows.append({
                        "timestamp": str(r["available_from"].date()),
                        "event": str(r.get("signal_name", r.get("source_name", "signal"))),
                        "detail": f"value={r.get('value', '')} · {r.get('source_name', '')}",
                        "family": str(r.get("signal_family", r.get("source_type", "signal"))),
                    })

        # Official visibility change after as_of (for replay truth) is NOT included here
        if not rows:
            return pd.DataFrame(columns=["timestamp", "event", "detail", "family"])
        out = pd.DataFrame(rows).drop_duplicates(subset=["timestamp", "event"])
        return out.sort_values("timestamp").reset_index(drop=True)

    def provenance_for_entity(self, country: str, disease: str, as_of: str, *, limit: int = 40) -> pd.DataFrame:
        if self.provenance.empty:
            return pd.DataFrame({"note": ["No provenance ledger loaded (run ingest to create data/interim/provenance.parquet)."]})
        frame = self.provenance.copy()
        if "available_from" in frame.columns:
            frame["available_from"] = pd.to_datetime(frame["available_from"], errors="coerce")
            frame = frame.loc[frame["available_from"] <= pd.Timestamp(as_of)]
        # Provenance may not carry entity_key; filter loosely by notes/query if needed
        cols = [c for c in (
            "source_name", "record_id", "source_type", "source_tier", "evidence_cluster",
            "published_at", "available_from", "retrieved_at", "url", "is_downstream_of_official",
            "realism", "reliability", "derived_from",
        ) if c in frame.columns]
        if not cols:
            return frame.head(limit)
        return frame[cols].sort_values(
            "available_from" if "available_from" in cols else cols[0],
            ascending=False,
        ).head(limit)

    def replay(self, entity_key: str, as_of: str) -> dict:
        """What the system knew at as_of vs what became officially visible afterwards."""
        series = self.entity_series(entity_key)
        as_of_ts = pd.Timestamp(as_of)
        then = series.loc[pd.to_datetime(series["as_of_date"]) == as_of_ts]
        if then.empty:
            return {"ok": False, "message": f"No prediction row for {entity_key} at {as_of}."}
        row = then.iloc[0]

        # First time alert left NONE/INFO at or before as_of
        prior = series.loc[pd.to_datetime(series["as_of_date"]) <= as_of_ts]
        alerted = prior.loc[~prior["alert_level"].isin(["NONE", "INFO"])]
        first_alert = alerted.iloc[0]["as_of_date"] if not alerted.empty else None

        # Subsequent official burden from observed_final if available
        future_official = None
        lead_days = None
        if not self.observed_final.empty:
            obs = self.observed_final.loc[self.observed_final["entity_key"] == entity_key].copy()
            if not obs.empty and "week_start" in obs.columns:
                obs["week_start"] = pd.to_datetime(obs["week_start"])
                after = obs.loc[
                    (obs["week_start"] > as_of_ts)
                    & (obs["week_start"] <= as_of_ts + pd.Timedelta(days=28))
                    & (obs["reported_final"] > 0)
                ]
                if not after.empty:
                    first_official = after["week_start"].min()
                    future_official = float(after["reported_final"].sum())
                    if first_alert is not None:
                        lead_days = (pd.Timestamp(first_official) - pd.Timestamp(first_alert)).days

        return {
            "ok": True,
            "as_of": as_of,
            "entity_key": entity_key,
            "known_then": {
                "alert_level": str(row["alert_level"]),
                "early_warning_probability": float(row["early_warning_probability"]),
                "latent_mean": float(row["latent_mean"]),
                "observed": float(row["observed"]),
                "reporting_gap": float(row["reporting_gap"]),
                "forecast_14d": float(row["forecast_14d"]) if pd.notna(row.get("forecast_14d")) else None,
            },
            "first_model_alert_date": str(first_alert)[:10] if first_alert is not None else None,
            "official_burden_next_28d": future_official,
            "lead_time_days": lead_days,
        }
