"""Forecast and historical replay screen."""

from __future__ import annotations

import math

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
    # Support both 0–1 and 0–100 encodings
    if x > 1.0:
        x = x / 100.0
    return f"{x:.0%}"


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
        h = input.fc_horizon()
        point = r.get(f"forecast_{h}d")
        lo = r.get(f"forecast_{h}d_lower")
        hi = r.get(f"forecast_{h}d_upper")
        return ui.layout_columns(
            ui.value_box(
                f"Forecast · {h} days (median)",
                f"{point:.1f}" if point == point else "n/a",
                showcase=ui.span("central short-term estimate", class_="small text-muted"),
            ),
            ui.value_box(
                "Uncertainty interval",
                f"{lo:.1f} – {hi:.1f}" if lo == lo else "n/a",
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
        fig = go.Figure()
        colours = {"7": "#88c0d0", "14": "#ebcb8b", "28": "#bf616a"}
        for h, colour in colours.items():
            col = f"forecast_{h}d"
            lo = f"forecast_{h}d_lower"
            hi = f"forecast_{h}d_upper"
            if col not in frame.columns:
                continue
            fig.add_trace(go.Scatter(
                x=frame["as_of_date"], y=frame[hi], line=dict(width=0), showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=frame["as_of_date"], y=frame[lo], fill="tonexty", name=f"{h}d interval",
                line=dict(width=0), fillcolor="rgba(136,192,208,0.15)",
            ))
            fig.add_trace(go.Scatter(
                x=frame["as_of_date"], y=frame[col], name=f"Forecast {h}d",
                line=dict(color=colour, width=2),
            ))
        fig.add_trace(go.Scatter(
            x=frame["as_of_date"], y=frame["observed"], name="Observed official",
            line=dict(color="#eceff4", dash="dot"),
        ))
        as_of = selected_as_of(input)
        fig.add_vline(x=as_of, line_dash="dash", line_color="#a3be8c")
        fig.update_layout(
            title=(
                "Short-term probabilistic forecasts vs official observation "
                f"(cut-off {as_of}) · MODEL ESTIMATE"
            ),
            height=440, paper_bgcolor="#0b1220", plot_bgcolor="#121a2b",
            font_color="#e5e9f0", legend=dict(orientation="h"),
            margin=dict(l=40, r=20, t=60, b=40),
            yaxis_title="Burden index (model scale)",
            xaxis_title="As-of week",
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.ui
    def fc_replay_summary():
        payload = replay_payload()
        if not payload.get("ok"):
            return ui.p(payload.get("message", "Replay unavailable."), class_="text-muted")
        known = payload["known_then"]
        lead = payload.get("lead_time_days")
        lead_txt = (
            f"{lead} days"
            if lead is not None
            else "n/a (no subsequent official activity in window, or no prior alert)"
        )
        country = selected_country(input)
        disease = case_disease(input)
        return ui.div(
            ui.h5(
                f"Replay snapshot · {country} · {disease} · as-of {payload['as_of']}",
                class_="h6",
            ),
            ui.p(
                "This reconstructs the model state using only information available on the as-of date, "
                "then compares it with official outcomes that arrived later (evaluation labels).",
                class_="small text-muted",
            ),
            ui.tags.ul(
                ui.tags.li(ui.tags.strong("Alert then: "), f"{known['alert_level']} (MODEL ESTIMATE)"),
                ui.tags.li(
                    ui.tags.strong("Early-warning probability then: "),
                    f"{known['early_warning_probability']:.0%}",
                ),
                ui.tags.li(
                    ui.tags.strong("Latent vs observed then: "),
                    f"{known['latent_mean']:.1f} vs {known['observed']:.1f} "
                    f"(gap {known['reporting_gap']:.0%})",
                ),
                ui.tags.li(ui.tags.strong("Forecast 14d then: "), f"{known['forecast_14d']}"),
                ui.tags.li(
                    ui.tags.strong("First model alert date: "),
                    f"{payload.get('first_model_alert_date') or 'none in window'}",
                ),
                ui.tags.li(
                    ui.tags.strong("Official burden in next 28d (final vintage): "),
                    f"{payload.get('official_burden_next_28d')}",
                ),
                ui.tags.li(
                    ui.tags.strong("Lead time (first alert → later official rise): "),
                    lead_txt,
                ),
            ),
            ui.p(
                "Lead time uses eventually-reported official counts after as-of — evaluation only, "
                "never as a feature input.",
                class_="small text-muted mb-2",
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
