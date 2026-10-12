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
    smr_covariates: pd.DataFrame = field(default_factory=pd.DataFrame)

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

        smr_covariates = pd.DataFrame()
        cov_path = interim / "covariates.parquet"
        if cov_path.exists():
            cov = read_parquet(cov_path)
            if not cov.empty and "variable" in cov.columns:
                smr_covariates = cov.loc[
                    cov["variable"].astype(str).str.startswith("smr_")
                ].copy()
                keep = [c for c in (
                    "country_iso3", "disease", "reference_date", "available_from",
                    "variable", "value", "unit", "source_name",
                ) if c in smr_covariates.columns]
                smr_covariates = smr_covariates[keep] if keep else smr_covariates

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
            smr_covariates=smr_covariates,
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

        # Prefer provenance linked to this country × disease via signals.
        if not self.signals.empty and "provenance_id" in self.signals.columns:
            sig = self.signals
            if "country_iso3" in sig.columns:
                sig = sig.loc[sig["country_iso3"].astype(str) == str(country)]
            if "disease" in sig.columns:
                sig = sig.loc[sig["disease"].astype(str) == str(disease)]
            if "available_from" in sig.columns:
                sig = sig.loc[pd.to_datetime(sig["available_from"], errors="coerce") <= pd.Timestamp(as_of)]
            prov_ids = set(sig["provenance_id"].dropna().astype(str).unique())
            if prov_ids and "provenance_id" in frame.columns:
                linked = frame.loc[frame["provenance_id"].astype(str).isin(prov_ids)]
                if not linked.empty:
                    frame = linked
            elif "record_id" in frame.columns:
                # Fall back: weekly aggregate ids often embed ISO3 + disease.
                key = f"{country}-{disease}"
                matched = frame.loc[frame["record_id"].astype(str).str.contains(key, case=False, na=False)]
                if not matched.empty:
                    frame = matched

        cols = [c for c in (
            "source_name", "record_id", "source_type", "source_tier", "evidence_cluster",
            "published_at", "available_from", "url", "notes", "realism", "reliability",
        ) if c in frame.columns]
        if not cols:
            return frame.head(limit)
        return frame[cols].sort_values(
            "available_from" if "available_from" in cols else cols[0],
            ascending=False,
        ).head(limit)

    def media_headlines_for_entity(
        self, country: str, disease: str, as_of: str, *, limit: int = 20
    ) -> pd.DataFrame:
        """Recent media/intelligence headlines for this case (title text, not full article bodies)."""
        as_of_ts = pd.Timestamp(as_of)
        rows: list[dict] = []
        raw = self.project_root / "data" / "raw"

        padi = raw / "padiweb" / "padiweb_articles_panel.csv"
        if padi.exists():
            try:
                df = pd.read_csv(
                    padi,
                    usecols=lambda c: c in {
                        "article_id", "published_date", "iso3", "disease_code",
                        "title", "url", "source_outlet", "data_realism",
                    },
                )
                df["published_date"] = pd.to_datetime(df["published_date"], errors="coerce")
                hit = df.loc[
                    (df["iso3"].astype(str) == str(country))
                    & (df["disease_code"].astype(str) == str(disease))
                    & (df["published_date"] <= as_of_ts)
                    & df["title"].notna()
                ].sort_values("published_date", ascending=False)
                for _, r in hit.head(limit).iterrows():
                    rows.append({
                        "published": str(r["published_date"])[:10],
                        "source": "PADI-web",
                        "outlet": r.get("source_outlet") or "",
                        "headline": str(r["title"]).strip(),
                        "url": r.get("url") or "",
                    })
            except Exception:
                pass

        beacon = raw / "beacon" / "beacon_reports_panel.csv"
        if beacon.exists():
            try:
                df = pd.read_csv(
                    beacon,
                    usecols=lambda c: c in {
                        "report_id", "detected_date", "screened_date", "iso3",
                        "disease_code", "title", "url", "data_realism",
                    },
                )
                date_col = "detected_date" if "detected_date" in df.columns else "screened_date"
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                hit = df.loc[
                    (df["iso3"].astype(str) == str(country))
                    & (df["disease_code"].astype(str) == str(disease))
                    & (df[date_col] <= as_of_ts)
                    & df["title"].notna()
                ].sort_values(date_col, ascending=False)
                for _, r in hit.head(limit).iterrows():
                    rows.append({
                        "published": str(r[date_col])[:10],
                        "source": "BEACON",
                        "outlet": "BEACON",
                        "headline": str(r["title"]).strip(),
                        "url": r.get("url") or "",
                    })
            except Exception:
                pass

        eios = raw / "eios" / "eios_newsmap_panel.csv"
        if eios.exists():
            try:
                df = pd.read_csv(eios, nrows=50000)
                cols = {c.lower(): c for c in df.columns}
                iso_c = cols.get("iso3") or cols.get("country_iso3")
                dis_c = cols.get("disease_code") or cols.get("disease")
                title_c = cols.get("title") or cols.get("headline")
                date_c = cols.get("published_date") or cols.get("date") or cols.get("detected_date")
                url_c = cols.get("url")
                if iso_c and dis_c and title_c and date_c:
                    df[date_c] = pd.to_datetime(df[date_c], errors="coerce")
                    hit = df.loc[
                        (df[iso_c].astype(str) == str(country))
                        & (df[dis_c].astype(str) == str(disease))
                        & (df[date_c] <= as_of_ts)
                        & df[title_c].notna()
                    ].sort_values(date_c, ascending=False)
                    for _, r in hit.head(min(limit, 10)).iterrows():
                        rows.append({
                            "published": str(r[date_c])[:10],
                            "source": "EIOS",
                            "outlet": "EIOS",
                            "headline": str(r[title_c]).strip(),
                            "url": str(r[url_c]) if url_c and pd.notna(r.get(url_c)) else "",
                        })
            except Exception:
                pass

        if not rows:
            return pd.DataFrame(columns=["published", "source", "outlet", "headline", "url"])
        out = pd.DataFrame(rows).drop_duplicates(subset=["headline"]).sort_values(
            "published", ascending=False
        )
        return out.head(limit)

    def _first_alert_crossing(self, series: pd.DataFrame, levels: set[str]) -> str | None:
        if series.empty or "alert_level" not in series.columns:
            return None
        frame = series.sort_values("as_of_date")
        hit = frame.loc[frame["alert_level"].isin(levels)]
        if hit.empty:
            return None
        return str(hit.iloc[0]["as_of_date"])[:10]

    def _smr_validation(self, entity_key: str, as_of: str, model_marker: str | None) -> dict:
        """Secondary official check via Six-Month Reports (not INFUR outbreak events).

        Looks for an SMR semester whose disease period overlaps the as-of / model
        alert window and whose report becomes knowable after the as-of (or after
        the model marker). Used when INFUR is silent after the cut-off.
        """
        empty = {
            "smr_found": False,
            "smr_present": False,
            "smr_semester_end": None,
            "smr_report_knowable_from": None,
            "smr_new_outbreaks": None,
            "smr_total_outbreaks": None,
            "smr_validates_model": False,
            "smr_lead_days_to_report": None,
            "smr_note": (
                "No SMR covariates loaded for this entity "
                "(run ingest with offline SMR extracts under data/raw/)."
                if self.smr_covariates.empty
                else "No overlapping SMR semester found for this country × disease."
            ),
        }
        if self.smr_covariates.empty or "|" not in entity_key:
            return empty
        country, disease = entity_key.split("|", 1)
        as_of_ts = pd.Timestamp(as_of)
        marker_ts = pd.Timestamp(model_marker) if model_marker else as_of_ts

        frame = self.smr_covariates.loc[
            (self.smr_covariates["country_iso3"].astype(str) == country)
            & (self.smr_covariates["disease"].astype(str) == disease)
        ].copy()
        if frame.empty:
            empty["smr_note"] = "No SMR rows for this country × disease in covariates."
            return empty

        frame["available_from"] = pd.to_datetime(frame["available_from"], errors="coerce")
        frame["reference_date"] = pd.to_datetime(frame["reference_date"], errors="coerce")
        # Semester window: ~182 days before semester-end reference.
        frame["semester_start"] = frame["reference_date"] - pd.Timedelta(days=183)

        # Prefer semesters knowable after as-of that cover the alert / as-of period.
        later = frame.loc[frame["available_from"] > as_of_ts]
        if later.empty:
            empty["smr_note"] = (
                "SMR exists for this case, but no semester report became knowable "
                "after this as-of in the loaded extract."
            )
            return empty

        def _priority(row: pd.Series) -> tuple:
            """0 = overlaps alert/as-of; 1 = just-closed semester; 2 = later semester."""
            start, end, avail = row["semester_start"], row["reference_date"], row["available_from"]
            if pd.isna(start) or pd.isna(end) or pd.isna(avail):
                return (9, pd.Timestamp.max)
            overlaps = bool(start <= marker_ts <= end or start <= as_of_ts <= end)
            just_closed = bool(end < as_of_ts and (as_of_ts - end).days <= 45)
            if overlaps:
                tier = 0
            elif just_closed:
                tier = 1
            else:
                tier = 2
            return (tier, avail)

        ranked = later.copy()
        ranked["_prio"] = ranked.apply(_priority, axis=1)
        ranked["_tier"] = ranked["_prio"].map(lambda p: p[0])
        # Prefer near-term supporting reports (earliest knowable among overlap /
        # just-closed), not the latest overlapping semester that arrives much later.
        near = ranked.loc[ranked["_tier"] <= 1]
        pool = near if not near.empty else ranked
        pool = pool.sort_values(["available_from", "_tier"])
        best = pool.iloc[0]
        semester_key = best["reference_date"]
        cover_tier = int(best["_tier"])
        sem = later.loc[later["reference_date"] == semester_key]
        knowable = pd.Timestamp(sem["available_from"].min())

        def _val(variable: str) -> float | None:
            hit = sem.loc[sem["variable"] == variable]
            if hit.empty:
                return None
            try:
                return float(hit.iloc[0]["value"])
            except (TypeError, ValueError):
                return None

        present = (_val("smr_disease_present") or 0.0) >= 0.5
        new_ob = _val("smr_new_outbreaks")
        total_ob = _val("smr_total_outbreaks")
        validates = bool(
            present or (new_ob is not None and new_ob > 0) or (total_ob is not None and total_ob > 0)
        )
        lead = (knowable - marker_ts).days if model_marker else (knowable - as_of_ts).days

        note = (
            f"SMR semester ending {str(semester_key)[:10]} became knowable on {str(knowable)[:10]}. "
            f"Disease present={present}; new outbreaks={new_ob}; total outbreaks={total_ob}. "
            "This is semester status — not an INFUR outbreak event."
        )
        if validates and cover_tier == 0:
            note += (
                " Semester overlaps the model alert / as-of window → supporting official "
                "validation when INFUR is silent."
            )
        elif validates and cover_tier == 1:
            note += (
                " Just-closed semester (ended within ~45 days before as-of) reported later — "
                "useful when endemic/stable situations leave INFUR; still coarse grain."
            )
        elif validates:
            note += (
                " Later semester report after as-of; period may only loosely relate to the "
                "alert week (coarse grain)."
            )

        return {
            "smr_found": True,
            "smr_present": present,
            "smr_semester_end": str(semester_key)[:10],
            "smr_report_knowable_from": str(knowable)[:10],
            "smr_new_outbreaks": new_ob,
            "smr_total_outbreaks": total_ob,
            "smr_validates_model": validates,
            "smr_lead_days_to_report": int(lead),
            "smr_note": note,
        }

    def replay(self, entity_key: str, as_of: str) -> dict:
        """What the system knew at as_of vs what became officially visible afterwards.

        Returns a narrative-ready storyline: intelligence → model alert → official report,
        with lead time when a later official report exists.
        """
        series = self.entity_series(entity_key)
        as_of_ts = pd.Timestamp(as_of)
        then = series.loc[pd.to_datetime(series["as_of_date"]) == as_of_ts]
        if then.empty:
            return {"ok": False, "message": f"No prediction row for {entity_key} at {as_of}."}
        row = then.iloc[0]

        # Model alert crossings over the full scored series (not only ≤ as_of),
        # so replay can show escalation after the cut-off as evaluation context.
        first_watch = self._first_alert_crossing(series, {"WATCH", "ALERT", "CRITICAL"})
        first_alert = self._first_alert_crossing(series, {"ALERT", "CRITICAL"})
        first_critical = self._first_alert_crossing(series, {"CRITICAL"})

        # Prefer first escalation at or before as_of for "what would we have known then?"
        prior = series.loc[pd.to_datetime(series["as_of_date"]) <= as_of_ts]
        first_watch_by_asof = self._first_alert_crossing(prior, {"WATCH", "ALERT", "CRITICAL"})
        first_alert_by_asof = self._first_alert_crossing(prior, {"ALERT", "CRITICAL"})

        # Official final vintage (evaluation labels — not model inputs)
        last_official_before = None
        last_official_before_count = None
        first_official_after = None
        first_official_after_count = None
        official_burden_next_28d = None
        official_burden_next_90d = None

        if not self.observed_final.empty:
            obs = self.observed_final.loc[self.observed_final["entity_key"] == entity_key].copy()
            if not obs.empty and "week_start" in obs.columns:
                obs["week_start"] = pd.to_datetime(obs["week_start"])
                before = obs.loc[(obs["week_start"] <= as_of_ts) & (obs["reported_final"] > 0)]
                if not before.empty:
                    last = before.sort_values("week_start").iloc[-1]
                    last_official_before = str(last["week_start"])[:10]
                    last_official_before_count = float(last["reported_final"])
                after = obs.loc[(obs["week_start"] > as_of_ts) & (obs["reported_final"] > 0)]
                if not after.empty:
                    first = after.sort_values("week_start").iloc[0]
                    first_official_after = str(first["week_start"])[:10]
                    first_official_after_count = float(first["reported_final"])
                    official_burden_next_90d = float(
                        after.loc[after["week_start"] <= as_of_ts + pd.Timedelta(days=90), "reported_final"].sum()
                    )
                    official_burden_next_28d = float(
                        after.loc[after["week_start"] <= as_of_ts + pd.Timedelta(days=28), "reported_final"].sum()
                    )

        # Intelligence signal activity knowable at as_of
        intel_sources_at_asof: list[str] = []
        intel_first_date = None
        intel_n_at_asof = 0
        if not self.signals.empty and "entity_key" in self.signals.columns:
            sig = self.signals.loc[self.signals["entity_key"] == entity_key].copy()
            if not sig.empty and "available_from" in sig.columns:
                sig["available_from"] = pd.to_datetime(sig["available_from"], errors="coerce")
                known = sig.loc[sig["available_from"] <= as_of_ts]
                intel_n_at_asof = int(len(known))
                if not known.empty:
                    intel_first_date = str(known["available_from"].min())[:10]
                    if "source_name" in known.columns:
                        intel_sources_at_asof = (
                            known["source_name"].astype(str).value_counts().head(6).index.tolist()
                        )

        # Lead time: model concern → later official INFUR report
        model_marker = first_alert_by_asof or first_watch_by_asof or first_alert or first_watch
        lead_days = None
        lead_basis = None
        if model_marker and first_official_after:
            lead_days = (pd.Timestamp(first_official_after) - pd.Timestamp(model_marker)).days
            lead_basis = (
                f"from model {('ALERT' if first_alert_by_asof or (first_alert and pd.Timestamp(first_alert) <= as_of_ts) else 'WATCH')} "
                f"on {model_marker} → official INFUR week {first_official_after}"
            )

        # Days since last official INFUR report (ongoing / silent gap)
        days_since_last_official = None
        if last_official_before:
            days_since_last_official = (as_of_ts - pd.Timestamp(last_official_before)).days

        smr = self._smr_validation(entity_key, as_of, model_marker)

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
            "story": {
                "intel_n_at_asof": intel_n_at_asof,
                "intel_first_date": intel_first_date,
                "intel_sources_at_asof": intel_sources_at_asof,
                "first_watch_date": first_watch_by_asof or first_watch,
                "first_alert_date": first_alert_by_asof or first_alert,
                "first_critical_date": first_critical,
                "first_watch_in_series": first_watch,
                "first_alert_in_series": first_alert,
                "alert_at_as_of": str(row["alert_level"]),
                "last_official_before_as_of": last_official_before,
                "last_official_before_count": last_official_before_count,
                "days_since_last_official": days_since_last_official,
                "first_official_after_as_of": first_official_after,
                "first_official_after_count": first_official_after_count,
                "official_burden_next_28d": official_burden_next_28d,
                "official_burden_next_90d": official_burden_next_90d,
                "lead_time_days": lead_days,
                "lead_basis": lead_basis,
                **smr,
            },
            # Back-compat keys used elsewhere
            "first_model_alert_date": first_watch_by_asof or first_watch,
            "official_burden_next_28d": official_burden_next_28d,
            "lead_time_days": lead_days,
        }
