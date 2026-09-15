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
        as_of = str(input.fc_as_of())
        hit = frame.loc[frame["as_of_date"].astype(str) == as_of]
        return hit.iloc[0] if len(hit) else None

    @render.ui
    def fc_summary():
        r = current_row()
        if r is None:
            return ui.p("No forecast for this selection.")
        h = input.fc_horizon()
        point = r.get(f"forecast_{h}d")
        lo = r.get(f"forecast_{h}d_lower")
        hi = r.get(f"forecast_{h}d_upper")
        return ui.layout_columns(
            ui.value_box(f"Forecast {h}d (median)", f"{point:.1f}" if point == point else "n/a"),
            ui.value_box("80–95% style interval", f"{lo:.1f} – {hi:.1f}" if lo == lo else "n/a"),
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
        for h, colour in (("7", "#88c0d0"), ("14", "#ebcb8b"), ("28", "#bf616a")):
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
                line=dict(width=0), fillcolor=colour.replace(")", ",0.2)").replace("rgb", "rgba")
                if colour.startswith("rgb") else f"rgba(136,192,208,0.15)",
            ))
            fig.add_trace(go.Scatter(
                x=frame["as_of_date"], y=frame[col], name=f"Forecast {h}d",
                line=dict(color=colour, width=2),
            ))
        fig.add_trace(go.Scatter(
            x=frame["as_of_date"], y=frame["observed"], name="Observed official",
            line=dict(color="#eceff4", dash="dot"),
        ))
        fig.update_layout(
            title="Probabilistic short-term forecasts (MODEL ESTIMATE)",
            height=440, paper_bgcolor="#0b1220", plot_bgcolor="#121a2b",
            font_color="#e5e9f0", legend=dict(orientation="h"),
            margin=dict(l=40, r=20, t=50, b=40),
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.data_frame
    def fc_replay_table():
        frame = series()
        cols = [
            "as_of_date", "observed", "latent_mean", "reporting_gap",
            "early_warning_probability", "alert_level",
            "forecast_7d", "forecast_14d", "forecast_28d", "confidence",
        ]
        cols = [c for c in cols if c in frame.columns]
        return render.DataGrid(frame[cols], height="360px")
