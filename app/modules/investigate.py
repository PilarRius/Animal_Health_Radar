"""Investigate screen."""

from __future__ import annotations

import plotly.graph_objects as go
from shiny import reactive, render, ui


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @reactive.calc
    def entity_key():
        return f"{input.inv_country()}|{input.inv_disease()}"

    @reactive.calc
    def row():
        key = entity_key()
        as_of = str(input.as_of_inv())
        frame = data.predictions
        hit = frame.loc[
            (frame["entity_key"] == key) & (frame["as_of_date"].astype(str) == as_of)
        ]
        return hit.iloc[0] if len(hit) else None

    @render.ui
    def inv_header():
        r = row()
        if r is None:
            return ui.h3(f"{entity_key()} — no prediction at this as-of")
        return ui.div(
            ui.h3(f"{r['country']} · {r['disease']}"),
            ui.tags.span(
                f"Alert: {r['alert_level']}",
                class_="badge bg-warning text-dark me-2",
            ),
            ui.tags.span("MODEL ESTIMATE", class_="badge bg-secondary"),
        )

    @render.ui
    def inv_kpis():
        r = row()
        if r is None:
            return ui.p("Select a country/disease/as-of with available predictions.")
        return ui.layout_columns(
            ui.value_box("Observed burden", f"{r['observed']:.1f}"),
            ui.value_box("Estimated latent", f"{r['latent_mean']:.1f} [{r['latent_lower']:.1f}–{r['latent_upper']:.1f}]"),
            ui.value_box("Reporting gap", f"{r['reporting_gap']:.0%}"),
            ui.value_box("EW probability", f"{r['early_warning_probability']:.0%}"),
            ui.value_box("Expected delay", f"{r['expected_delay']:.0f} d"),
            ui.value_box("Forecast 14d", f"{r['forecast_14d']:.1f}" if r['forecast_14d'] == r['forecast_14d'] else "n/a"),
            col_widths=(2, 2, 2, 2, 2, 2),
        )

    @render.ui
    def inv_timeseries():
        series = data.entity_series(entity_key())
        if series.empty:
            return ui.p("No time series.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=series["as_of_date"], y=series["observed"], name="Observed (official)",
            line=dict(color="#88c0d0"),
        ))
        fig.add_trace(go.Scatter(
            x=series["as_of_date"], y=series["latent_upper"], name="Latent upper",
            line=dict(width=0), showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=series["as_of_date"], y=series["latent_lower"], name="Uncertainty",
            fill="tonexty", line=dict(width=0), fillcolor="rgba(191,97,106,0.25)",
        ))
        fig.add_trace(go.Scatter(
            x=series["as_of_date"], y=series["latent_mean"], name="Estimated latent activity",
            line=dict(color="#bf616a", width=2),
        ))
        fig.update_layout(
            title="Observed vs estimated latent activity (MODEL ESTIMATE)",
            height=420, margin=dict(l=40, r=20, t=50, b=40),
            paper_bgcolor="#0b1220", plot_bgcolor="#121a2b", font_color="#e5e9f0",
            legend=dict(orientation="h"),
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.ui
    def inv_why():
        r = row()
        if r is None:
            return ui.p("—")
        alert_id = f"AHR-{r['country']}-{r['disease']}-{r['as_of_date']}"
        explanation = data.explanation_for(alert_id)
        if not explanation:
            return ui.p("No explanation artefact for this alert.")
        return ui.div(
            ui.h5(explanation.get("headline", "")),
            ui.p(explanation.get("narrative", "")),
            ui.p(f"Method: {explanation.get('method', '')}", class_="small text-muted"),
        )

    @render.ui
    def inv_counterfactuals():
        r = row()
        if r is None:
            return ui.p("—")
        alert_id = f"AHR-{r['country']}-{r['disease']}-{r['as_of_date']}"
        explanation = data.explanation_for(alert_id) or {}
        items = explanation.get("counterfactuals") or []
        if not items:
            return ui.p("No counterfactuals computed.")
        blocks = []
        for item in items[:6]:
            blocks.append(
                ui.p(
                    f"{item.get('family')}: {item.get('probability_with', 0):.0%} → "
                    f"{item.get('probability_without', 0):.0%} "
                    f"({item.get('interpretation', '')})"
                )
            )
        return ui.div(*blocks)

    @render.data_frame
    def inv_evidence():
        r = row()
        if r is None:
            return render.DataGrid(data.predictions.head(0))
        alert_id = f"AHR-{r['country']}-{r['disease']}-{r['as_of_date']}"
        explanation = data.explanation_for(alert_id) or {}
        rows = explanation.get("top_contributions") or []
        import pandas as pd

        frame = pd.DataFrame(rows)
        if frame.empty:
            return render.DataGrid(pd.DataFrame({"note": ["No contributions"]}))
        keep = [c for c in ("feature", "family", "value", "contribution", "direction") if c in frame.columns]
        return render.DataGrid(frame[keep], height="280px")
