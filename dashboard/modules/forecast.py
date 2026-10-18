"""Forecast and historical replay screen."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from shiny import reactive, render, ui

from dashboard.filter_state import case_disease, selected_as_of, selected_country


def _fmt_prob(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(x):
        return "n/a"
    if x > 1.0:
        x = x / 100.0
    return f"{x:.0%}"


def _fmt_num(value, *, digits: int = 1) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(x):
        return "n/a"
    return f"{x:.{digits}f}"


def _as_timestamp(value) -> pd.Timestamp | None:
    """Parse chart / vline positions; plotly add_vline breaks on mixed str/int axes."""
    if value is None or value == "":
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts


def _add_vline(fig: go.Figure, x, *, text: str, color: str, dash: str, position: str) -> None:
    ts = _as_timestamp(x)
    if ts is None:
        return
    # annotation=None avoids plotly's shapeannotation._mean() path, which raises
    # TypeError when the x-axis still has mixed types.
    fig.add_vline(x=ts, line_dash=dash, line_color=color, annotation=None)
    fig.add_annotation(
        x=ts,
        y=1.02,
        yref="paper",
        text=text,
        showarrow=False,
        font=dict(size=10, color=color),
        xanchor="left" if "right" not in position else "right",
    )


def _story_block(title: str, body: str, *, tone: str = "neutral") -> ui.Tag:
    return ui.div(
        {"class": f"ahr-story-step ahr-story-{tone}"},
        ui.div({"class": "ahr-story-step-title"}, title),
        ui.p(str(body), class_="mb-0"),
    )


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @reactive.calc
    def entity_key():
        return f"{selected_country(input)}|{case_disease(input)}"

    @reactive.calc
    def series():
        return data.entity_series(entity_key())

    @reactive.calc
    def current_row():
        frame = series()
        as_of = selected_as_of(input)
        hit = frame.loc[frame["as_of_date"].astype(str) == as_of]
        return hit.iloc[0] if len(hit) else None

    @reactive.calc
    def replay_payload():
        return data.replay(entity_key(), selected_as_of(input))

    @render.ui
    def fc_summary():
        r = current_row()
        if r is None:
            return ui.p("No forecast for this selection at the global as-of. Try another country, disease, or as-of.")
        raw_h = str(input.fc_horizon() or "14").split()[0]
        h = raw_h if raw_h in {"7", "14", "28"} else "14"
        point = r.get(f"forecast_{h}d")
        lo = r.get(f"forecast_{h}d_lower")
        hi = r.get(f"forecast_{h}d_upper")
        return ui.layout_columns(
            ui.value_box(
                f"Forecast · {h} days (median)",
                _fmt_num(point),
                showcase=ui.span("central short-term estimate", class_="small text-muted"),
            ),
            ui.value_box(
                "Uncertainty interval",
                f"{_fmt_num(lo)} – {_fmt_num(hi)}",
                showcase=ui.span("predictive range, not error bars on truth", class_="small text-muted"),
            ),
            ui.value_box(
                "P(increase within 14d)",
                _fmt_prob(r.get("p_increase_14d")),
                showcase=ui.span("chance burden rises", class_="small text-muted"),
            ),
            ui.value_box(
                "P(new official visibility · 28d)",
                _fmt_prob(r.get("p_new_outbreak_28d")),
                showcase=ui.span("early-warning flavoured exceedance", class_="small text-muted"),
            ),
            col_widths=(3, 3, 3, 3),
        )

    @render.ui
    def fc_fan():
        frame = series()
        if frame.empty:
            return ui.p("No series.")
        frame = frame.copy()
        frame["as_of_date"] = pd.to_datetime(frame["as_of_date"], errors="coerce")
        frame = frame.dropna(subset=["as_of_date"]).sort_values("as_of_date")
        if frame.empty:
            return ui.p("No dated forecast series for this selection.")
        payload = replay_payload()
        story = (payload.get("story") or {}) if payload.get("ok") else {}
        fig = go.Figure()
        colours = {"7": "#88c0d0", "14": "#ebcb8b", "28": "#bf616a"}
        x = frame["as_of_date"]
        for h, colour in colours.items():
            col = f"forecast_{h}d"
            lo = f"forecast_{h}d_lower"
            hi = f"forecast_{h}d_upper"
            if col not in frame.columns:
                continue
            fig.add_trace(go.Scatter(
                x=x, y=frame[hi], line=dict(width=0), showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=x, y=frame[lo], fill="tonexty", name=f"{h}d interval",
                line=dict(width=0), fillcolor="rgba(136,192,208,0.15)",
            ))
            fig.add_trace(go.Scatter(
                x=x, y=frame[col], name=f"Forecast {h}d",
                line=dict(color=colour, width=2),
            ))
        fig.add_trace(go.Scatter(
            x=x, y=frame["observed"], name="Observed official (vintage)",
            line=dict(color="#eceff4", dash="dot"),
        ))
        as_of = selected_as_of(input)
        _add_vline(fig, as_of, text="as-of", color="#a3be8c", dash="dash", position="top left")
        watch = story.get("first_watch_date")
        alert = story.get("first_alert_date") or story.get("first_alert_in_series")
        official_after = story.get("first_official_after_as_of")
        official_before = story.get("last_official_before_as_of")
        if watch:
            _add_vline(fig, watch, text="model WATCH", color="#ebcb8b", dash="dot", position="top right")
        if alert and alert != watch:
            _add_vline(fig, alert, text="model ALERT", color="#bf616a", dash="dot", position="top right")
        if official_after:
            _add_vline(
                fig, official_after, text="official after", color="#88c0d0",
                dash="solid", position="bottom right",
            )
        elif official_before:
            _add_vline(
                fig, official_before, text="last official before", color="#5e81ac",
                dash="solid", position="bottom left",
            )
        fig.update_layout(
            title=(
                "Short-term forecasts vs official observation "
                f"(cut-off {as_of}) · MODEL ESTIMATE"
            ),
            height=440, paper_bgcolor="#0b1220", plot_bgcolor="#121a2b",
            font_color="#e5e9f0", legend=dict(orientation="h"),
            margin=dict(l=40, r=20, t=60, b=40),
            yaxis_title="Burden index (model scale)",
            xaxis_title="As-of week",
            xaxis=dict(type="date"),
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.ui
    def fc_replay_summary():
        payload = replay_payload()
        if not payload.get("ok"):
            return ui.p(payload.get("message", "Replay unavailable."), class_="text-muted")

        known = payload["known_then"]
        story = payload.get("story") or {}
        country = selected_country(input)
        disease = case_disease(input)
        country_spec = data.countries.get(country)
        country_label = country_spec.name if country_spec is not None else country

        intel_n = story.get("intel_n_at_asof") or 0
        intel_sources = story.get("intel_sources_at_asof") or []
        intel_first = story.get("intel_first_date")
        watch = story.get("first_watch_date")
        alert = story.get("first_alert_date") or story.get("first_alert_in_series")
        alert_then = story.get("alert_at_as_of") or known["alert_level"]
        last_off = story.get("last_official_before_as_of")
        last_off_n = story.get("last_official_before_count")
        days_since = story.get("days_since_last_official")
        next_off = story.get("first_official_after_as_of")
        next_off_n = story.get("first_official_after_count")
        lead = story.get("lead_time_days")
        lead_basis = story.get("lead_basis")
        burden_28 = story.get("official_burden_next_28d")
        burden_90 = story.get("official_burden_next_90d")

        # Step copy
        if intel_n:
            src = ", ".join(intel_sources[:4]) if intel_sources else "intelligence sources"
            intel_body = (
                f"{intel_n} intelligence signal rows were knowable by the as-of"
                + (f" (first seen {intel_first})" if intel_first else "")
                + f". Sources include {src}."
            )
            intel_tone = "info"
        else:
            intel_body = "No intelligence signal rows linked to this case under the as-of in the loaded panel."
            intel_tone = "neutral"

        if watch or alert:
            bits = []
            if watch:
                bits.append(f"first raised WATCH on {watch}")
            if alert:
                bits.append(f"escalated to ALERT on {alert}")
            model_body = (
                f"At the as-of cut-off the model state was {alert_then} "
                f"(early-warning probability {known['early_warning_probability']:.0%}). "
                f"In this series it {' and '.join(bits)}."
            )
            model_tone = "warn" if alert_then in ("WATCH", "ALERT", "CRITICAL") else "neutral"
        else:
            model_body = (
                f"At as-of the model was {alert_then} "
                f"(EW {known['early_warning_probability']:.0%}) and never crossed WATCH/ALERT in the scored window."
            )
            model_tone = "neutral"

        if last_off:
            off_before = (
                f"Last official INFUR activity (final vintage) before/at as-of: week of {last_off}"
                + (f" ({last_off_n:.0f} reported)" if last_off_n is not None else "")
                + (f" — {days_since} days before the as-of." if days_since is not None else ".")
            )
        else:
            off_before = (
                "No official INFUR reports (final vintage) on or before this as-of for this country × disease."
            )

        if next_off:
            off_after = (
                f"Next official INFUR report after as-of: week of {next_off}"
                + (f" ({next_off_n:.0f} reported)" if next_off_n is not None else "")
                + "."
            )
            if burden_28 is not None:
                off_after += f" Official burden in next 28d: {burden_28:.0f}."
            if burden_90 is not None and burden_90 != burden_28:
                off_after += f" Next 90d: {burden_90:.0f}."
            off_tone = "ok"
        else:
            off_after = (
                "No further official INFUR (Immediate Notification / Follow-Up) after this as-of "
                "in the loaded final-vintage panel. That does not prove absence of disease — "
                "endemic / ‘stable’ situations and some diseases may only appear later on SMR "
                "(see step 6)."
            )
            off_tone = "neutral"

        smr_found = bool(story.get("smr_found"))
        smr_validates = bool(story.get("smr_validates_model"))
        smr_note = str(story.get("smr_note") or "")
        smr_knowable = story.get("smr_report_knowable_from")
        smr_sem = story.get("smr_semester_end")
        smr_lead = story.get("smr_lead_days_to_report")

        if smr_found and smr_validates:
            smr_body = (
                f"Supporting SMR validation: semester ending {smr_sem} listed disease present / outbreaks "
                f"and became knowable on {smr_knowable}"
                f"{f' ({smr_lead} days after the model marker)' if smr_lead is not None else ''}."
                f" {smr_note}"
            )
            smr_tone = "ok"
        elif smr_found:
            smr_body = smr_note
            smr_tone = "info"
        else:
            smr_body = (
                f"{smr_note} Remember: once a situation is treated as endemic / stable, countries often stop "
                "event-driven INFUR and continue only via six-month reports; non-notifiable diseases "
                "may never appear on INFUR."
            )
            smr_tone = "neutral"

        if lead is not None and lead >= 0:
            lead_body = (
                f"INFUR lead time: the model raised concern {lead} days before the next INFUR report. "
                f"({lead_basis})"
            )
            lead_tone = "ok"
        elif lead is not None and lead < 0:
            lead_body = (
                f"INFUR report came {-lead} days before the model marker used for lead time "
                f"({lead_basis}). This cut-off is not an early-warning win on that INFUR episode."
            )
            lead_tone = "warn"
        elif smr_validates and smr_lead is not None and smr_lead >= 0 and (watch or alert):
            lead_body = (
                f"No later INFUR week, but SMR later acknowledged disease in an overlapping semester "
                f"({smr_lead} days after the model marker → SMR knowable {smr_knowable}). "
                "Treat as coarse semester validation, not day-level INFUR lead time."
            )
            lead_tone = "ok"
        elif last_off and not next_off and (watch or alert):
            lead_body = (
                "INFUR activity was already in the history before/at as-of, and no newer INFUR "
                "report appears after the cut-off. Check step 6 (SMR): endemic / stable situations "
                "often leave INFUR and only update on six-month reports."
            )
            lead_tone = "warn"
        else:
            lead_body = (
                "INFUR lead time not computed: need both a model WATCH/ALERT and a later INFUR "
                "report week. If INFUR is silent, use step 6 (SMR) as secondary validation only."
            )
            lead_tone = "neutral"

        return ui.div(
            {"class": "ahr-story"},
            ui.h5(
                f"Early-warning storyline · {country_label} · {disease} · as-of {payload['as_of']}",
                class_="h6 mb-2",
            ),
            ui.p(
                "Read top → bottom: intelligence → model concern → INFUR before/after as-of → "
                "INFUR lead time → SMR semester check (secondary official validation).",
                class_="small text-muted",
            ),
            _story_block("1 · Intelligence knowable at as-of", intel_body, tone=intel_tone),
            _story_block("2 · When the model raised concern", model_body, tone=model_tone),
            _story_block("3 · Official INFUR (before as-of)", off_before, tone="info"),
            _story_block("4 · Official INFUR (after as-of)", off_after, tone=off_tone),
            _story_block("5 · Lead time (model → INFUR)", lead_body, tone=lead_tone),
            _story_block("6 · SMR semester check (not an INFUR event)", smr_body, tone=smr_tone),
            ui.p(
                "INFUR dates use eventually-reported final vintages for evaluation only. "
                "SMR is semester status with a different ID space — never mixed into outbreak counts. "
                "Vertical lines on the chart mark INFUR / model milestones.",
                class_="small text-muted mt-2 mb-0",
            ),
        )

    @render.data_frame
    def fc_replay_table():
        frame = series()
        as_of = selected_as_of(input)
        frame = frame.copy()
        frame["as_of_date"] = frame["as_of_date"].astype(str)
        frame["replay_role"] = frame["as_of_date"].map(
            lambda d: "knowable_then" if d <= as_of else "after_as_of_outcome"
        )
        cols = [
            "as_of_date", "replay_role", "observed", "latent_mean", "reporting_gap",
            "early_warning_probability", "alert_level",
            "forecast_7d", "forecast_14d", "forecast_28d", "confidence",
        ]
        cols = [c for c in cols if c in frame.columns]
        view = frame[cols].copy()
        if "early_warning_probability" in view.columns:
            view["early_warning_probability"] = view["early_warning_probability"].map(
                lambda x: f"{x:.0%}" if x == x else "—"
            )
        if "reporting_gap" in view.columns:
            view["reporting_gap"] = view["reporting_gap"].map(
                lambda x: f"{x:.0%}" if x == x else "—"
            )
        view = view.rename(columns={
            "as_of_date": "As-of",
            "replay_role": "Role vs cut-off",
            "observed": "Observed",
            "latent_mean": "Latent (est.)",
            "reporting_gap": "Reporting gap",
            "early_warning_probability": "EW probability",
            "alert_level": "Alert",
            "forecast_7d": "Fcst 7d",
            "forecast_14d": "Fcst 14d",
            "forecast_28d": "Fcst 28d",
            "confidence": "Confidence",
        })
        return render.DataGrid(view, height="360px")
