"""Forecast and historical replay screen."""

from __future__ import annotations

import plotly.graph_objects as go
from shiny import reactive, render, ui


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @reactive.calc
    def entity_key():
        return f"{input.fc_country()}|{input.fc_disease()}"

    @reactive.calc
    def series():
        return data.entity_series(entity_key())

    @reactive.calc
    def current_row():
        frame = series()
        as_of = str(input.as_of())
        hit = frame.loc[frame["as_of_date"].astype(str) == as_of]
        return hit.iloc[0] if len(hit) else None

    @reactive.calc
    def replay_payload():
        return data.replay(entity_key(), str(input.as_of()))

    @render.ui
    def fc_summary():
        r = current_row()
        if r is None:
            return ui.p("No forecast for this selection at the global as-of.")
        h = input.fc_horizon()
        point = r.get(f"forecast_{h}d")
        lo = r.get(f"forecast_{h}d_lower")
        hi = r.get(f"forecast_{h}d_upper")
        return ui.layout_columns(
            ui.value_box(f"Forecast {h}d (median)", f"{point:.1f}" if point == point else "n/a"),
            ui.value_box("Interval", f"{lo:.1f} – {hi:.1f}" if lo == lo else "n/a"),
            ui.value_box("P(increase 14d)", f"{r.get('p_increase_14d', float('nan'))}"),
            ui.value_box("P(new outbreak 28d)", f"{r.get('p_new_outbreak_28d', float('nan'))}"),
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
        fig.add_vline(x=input.as_of(), line_dash="dash", line_color="#a3be8c")
        fig.update_layout(
            title="Probabilistic short-term forecasts (MODEL ESTIMATE)",
            height=440, paper_bgcolor="#0b1220", plot_bgcolor="#121a2b",
            font_color="#e5e9f0", legend=dict(orientation="h"),
            margin=dict(l=40, r=20, t=50, b=40),
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.ui
    def fc_replay_summary():
        payload = replay_payload()
        if not payload.get("ok"):
            return ui.p(payload.get("message", "Replay unavailable."), class_="text-muted")
        known = payload["known_then"]
        lead = payload.get("lead_time_days")
        lead_txt = f"{lead} days" if lead is not None else "n/a (no subsequent official activity in window, or no prior alert)"
        return ui.div(
            ui.h5(f"Replay at as-of {payload['as_of']} · {payload['entity_key']}"),
            ui.tags.ul(
                ui.tags.li(f"Alert then: {known['alert_level']} (MODEL ESTIMATE)"),
                ui.tags.li(f"EW probability then: {known['early_warning_probability']:.0%}"),
                ui.tags.li(
                    f"Latent {known['latent_mean']:.1f} vs observed {known['observed']:.1f} "
                    f"(gap {known['reporting_gap']:.0%})"
                ),
                ui.tags.li(f"Forecast 14d then: {known['forecast_14d']}"),
                ui.tags.li(f"First model alert date: {payload.get('first_model_alert_date') or 'none'}"),
                ui.tags.li(
                    f"Official burden in next 28d (final vintage): {payload.get('official_burden_next_28d')}"
                ),
                ui.tags.li(f"Lead time (first alert → first later official week): {lead_txt}"),
            ),
            ui.p(
                "Lead time uses eventually-reported official counts after as-of — evaluation only, "
                "never as a feature.",
                class_="small text-muted",
            ),
        )

    @render.data_frame
    def fc_replay_table():
        frame = series()
        as_of = str(input.as_of())
        # Show history up to as-of (what was knowable) plus a few later rows labelled as outcome
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
        return render.DataGrid(frame[cols], height="360px")
