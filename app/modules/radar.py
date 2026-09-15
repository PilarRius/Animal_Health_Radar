"""Global Radar screen."""

from __future__ import annotations

import plotly.express as px
from shiny import render, ui

ALERT_COLOURS = {
    "NONE": "#3b4252",
    "INFO": "#5e81ac",
    "WATCH": "#ebcb8b",
    "ALERT": "#d08770",
    "CRITICAL": "#bf616a",
}


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @render.ui
    def radar_kpis():
        frame = filtered_predictions()
        if frame.empty:
            return ui.p("No predictions for this as-of / disease.")
        n_priority = int((frame["investigation_priority"] >= 0.52).sum())
        n_alert = int(frame["alert_level"].isin(["ALERT", "CRITICAL"]).sum())
        mean_gap = float(frame["reporting_gap"].mean())
        return ui.layout_columns(
            ui.value_box("Entities", str(len(frame)), theme="bg-gradient-blue-purple"),
            ui.value_box("ALERT / CRITICAL", str(n_alert), theme="bg-gradient-orange-red"),
            ui.value_box("High priority", str(n_priority)),
            ui.value_box("Mean reporting gap", f"{mean_gap:.0%}"),
            col_widths=(3, 3, 3, 3),
        )

    @render.ui
    def radar_map():
        frame = filtered_predictions()
        if frame.empty:
            return ui.p("No map data.")
        layer = input.map_layer()
        plot_df = frame.copy()
        if layer not in plot_df.columns:
            layer = "investigation_priority"
        fig = px.choropleth(
            plot_df,
            locations="country",
            locationmode="ISO-3",
            color=layer,
            hover_name="country",
            hover_data={
                "disease": True,
                "early_warning_probability": ":.0%",
                "latent_mean": ":.1f",
                "observed": ":.1f",
                "reporting_gap": ":.0%",
                "forecast_14d": ":.1f",
                "alert_level": True,
                "confidence": ":.2f",
            },
            color_continuous_scale="YlOrRd",
            projection="natural earth",
            title=f"{layer.replace('_', ' ').title()} · as-of {input.as_of()}",
        )
        fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=520, paper_bgcolor="#0b1220",
                          plot_bgcolor="#0b1220", font_color="#e5e9f0",
                          geo=dict(bgcolor="#0b1220", lakecolor="#0b1220", landcolor="#1c2434"))
        # Embed as HTML div (avoid shinywidgets dependency issues)
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.data_frame
    def radar_table():
        frame = filtered_predictions()
        cols = [
            "country", "disease", "alert_level", "early_warning_probability",
            "latent_mean", "observed", "reporting_gap", "forecast_14d",
            "investigation_priority", "confidence",
        ]
        cols = [c for c in cols if c in frame.columns]
        return render.DataGrid(frame[cols].sort_values("investigation_priority", ascending=False), height="360px")
