"""Global Radar screen."""

from __future__ import annotations

import plotly.express as px
from shiny import render, ui

LAYER_TITLES = {
    "investigation_priority": "Investigation priority — where to look first",
    "early_warning_probability": "Early-warning probability — chance of rising official visibility (~28d)",
    "latent_mean": "Estimated latent activity — underlying burden nowcast",
    "reporting_gap": "Estimated reporting gap — latent vs official observation",
    "forecast_14d": "14-day forecast — expected short-term burden",
    "forecast_28d": "28-day forecast — expected medium-term burden",
    "environmental_signal": "Environmental context signal",
    "intelligence_signal": "Epidemic-intelligence context signal",
}

TABLE_RENAME = {
    "country": "Country",
    "disease": "Disease",
    "alert_level": "Alert",
    "early_warning_probability": "EW probability",
    "latent_mean": "Latent (est.)",
    "observed": "Observed (official)",
    "reporting_gap": "Reporting gap",
    "forecast_14d": "Forecast 14d",
    "investigation_priority": "Investigate priority",
    "confidence": "Confidence",
}


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @render.ui
    def radar_kpis():
        frame = filtered_predictions()
        if frame.empty:
            return ui.p("No predictions for this as-of / disease. Try another as-of or disease filter.")
        n_priority = int((frame["investigation_priority"] >= 0.52).sum())
        n_alert = int(frame["alert_level"].isin(["ALERT", "CRITICAL"]).sum())
        mean_gap = float(frame["reporting_gap"].mean())
        return ui.layout_columns(
            ui.value_box(
                "Places scored",
                str(len(frame)),
                showcase=ui.span("country × disease rows", class_="small text-muted"),
            ),
            ui.value_box(
                "ALERT / CRITICAL",
                str(n_alert),
                showcase=ui.span("need analyst attention", class_="small text-muted"),
            ),
            ui.value_box(
                "High investigation priority",
                str(n_priority),
                showcase=ui.span("priority ≥ 0.52", class_="small text-muted"),
            ),
            ui.value_box(
                "Mean reporting gap",
                f"{mean_gap:.0%}",
                showcase=ui.span("avg latent above observed", class_="small text-muted"),
            ),
            col_widths=(3, 3, 3, 3),
        )

    @render.ui
    def radar_map():
        frame = filtered_predictions()
        if frame.empty:
            return ui.p("No map data for this filter.")
        layer = input.map_layer()
        plot_df = frame.copy()
        if layer not in plot_df.columns:
            layer = "investigation_priority"
        title = LAYER_TITLES.get(layer, layer.replace("_", " ").title())
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
            title=f"{title} · as-of {input.as_of()} · MODEL ESTIMATE",
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=48, b=0),
            height=520,
            paper_bgcolor="#0b1220",
            plot_bgcolor="#0b1220",
            font_color="#e5e9f0",
            geo=dict(bgcolor="#0b1220", lakecolor="#0b1220", landcolor="#1c2434"),
            coloraxis_colorbar=dict(title=""),
        )
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
        view = frame[cols].sort_values("investigation_priority", ascending=False).copy()
        if "early_warning_probability" in view.columns:
            view["early_warning_probability"] = view["early_warning_probability"].map(
                lambda x: f"{x:.0%}" if x == x else "—"
            )
        if "reporting_gap" in view.columns:
            view["reporting_gap"] = view["reporting_gap"].map(
                lambda x: f"{x:.0%}" if x == x else "—"
            )
        view = view.rename(columns={c: TABLE_RENAME.get(c, c) for c in view.columns})
        return render.DataGrid(view, height="360px")
