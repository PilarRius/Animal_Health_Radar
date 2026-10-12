"""Investigate screen."""

from __future__ import annotations

import plotly.graph_objects as go
from shiny import reactive, render, ui

from dashboard.filter_state import case_disease, selected_as_of, selected_country


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    @reactive.calc
    def entity_key():
        return f"{selected_country(input)}|{case_disease(input)}"

    @reactive.calc
    def row():
        key = entity_key()
        as_of = selected_as_of(input)
        frame = data.predictions
        hit = frame.loc[
            (frame["entity_key"] == key) & (frame["as_of_date"].astype(str) == as_of)
        ]
        return hit.iloc[0] if len(hit) else None

    @render.ui
    def inv_header():
        r = row()
        as_of = selected_as_of(input)
        if r is None:
            return ui.div(
                {"class": "alert alert-secondary"},
                ui.h3(f"{entity_key()} — no prediction at as-of {as_of}", class_="h5 mb-1"),
                ui.p(
                    "Try another as-of date or disease. Not every country × disease × week has a scored row.",
                    class_="mb-0 small",
                ),
            )
        country_name = data.countries.get(str(r["country"]))
        country_label = country_name.name if country_name is not None else r["country"]
        disease_name = data.diseases.get(str(r["disease"]))
        disease_label = disease_name.name if disease_name is not None else r["disease"]
        return ui.div(
            ui.h3(f"{country_label} · {disease_label}", class_="mb-2"),
            ui.tags.span(f"Alert: {r['alert_level']}", class_="badge bg-warning text-dark me-2"),
            ui.tags.span("MODEL ESTIMATE", class_="badge bg-secondary me-2"),
            ui.tags.span(f"as-of {as_of}", class_="badge bg-dark me-2"),
            ui.tags.span(
                "Compare official observation with estimated latent activity",
                class_="small text-muted",
            ),
        )

    @render.ui
    def inv_kpis():
        r = row()
        if r is None:
            return ui.p("Select a country/disease with available predictions at the global as-of.")
        f14 = r["forecast_14d"]
        return ui.layout_columns(
            ui.value_box(
                "Observed (official)",
                f"{r['observed']:.1f}",
                showcase=ui.span("what is already visible", class_="small text-muted"),
            ),
            ui.value_box(
                "Estimated latent",
                f"{r['latent_mean']:.1f} [{r['latent_lower']:.1f}–{r['latent_upper']:.1f}]",
                showcase=ui.span("nowcast + uncertainty", class_="small text-muted"),
            ),
            ui.value_box(
                "Reporting gap",
                f"{r['reporting_gap']:.0%}",
                showcase=ui.span("latent above observed", class_="small text-muted"),
            ),
            ui.value_box(
                "Early-warning probability",
                f"{r['early_warning_probability']:.0%}",
                showcase=ui.span("~28d official visibility risk", class_="small text-muted"),
            ),
            ui.value_box(
                "Expected reporting delay",
                f"{r['expected_delay']:.0f} d",
                showcase=ui.span("onset → official visibility", class_="small text-muted"),
            ),
            ui.value_box(
                "Forecast · 14 days",
                f"{f14:.1f}" if f14 == f14 else "n/a",
                showcase=ui.span("short-term trajectory", class_="small text-muted"),
            ),
            col_widths=(2, 2, 2, 2, 2, 2),
        )

    @render.ui
    def inv_timeseries():
        series = data.entity_series(entity_key())
        if series.empty:
            return ui.p("No time series for this case.")
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
            x=series["as_of_date"], y=series["latent_lower"], name="Latent uncertainty band",
            fill="tonexty", line=dict(width=0), fillcolor="rgba(191,97,106,0.25)",
        ))
        fig.add_trace(go.Scatter(
            x=series["as_of_date"], y=series["latent_mean"], name="Estimated latent activity",
            line=dict(color="#bf616a", width=2),
        ))
        as_of = selected_as_of(input)
        fig.add_vline(x=as_of, line_dash="dash", line_color="#ebcb8b")
        fig.update_layout(
            title=(
                "Nowcast: official observed vs estimated latent activity "
                f"(as-of cut-off = {as_of}) · MODEL ESTIMATE"
            ),
            height=420, margin=dict(l=40, r=20, t=60, b=40),
            paper_bgcolor="#0b1220", plot_bgcolor="#121a2b", font_color="#e5e9f0",
            legend=dict(orientation="h"),
            yaxis_title="Burden index (model scale)",
            xaxis_title="As-of week",
        )
        return ui.HTML(fig.to_html(include_plotlyjs="cdn", full_html=False))

    @render.ui
    def inv_timeline():
        timeline = data.evidence_timeline(entity_key(), selected_as_of(input))
        if timeline.empty:
            return ui.p(
                "No timeline events under this as-of yet. "
                "That can mean sparse intelligence for this case, or that the model has not crossed WATCH/ALERT. "
                "Still use the latent-vs-observed chart and contributions below.",
                class_="text-muted",
            )
        items = []
        for _, r in timeline.iterrows():
            items.append(
                ui.tags.li(
                    ui.tags.strong(f"{r['timestamp']} · {r['event']}"),
                    ui.tags.span(f" [{r['family']}] ", class_="text-muted"),
                    ui.tags.span(str(r["detail"])),
                )
            )
        return ui.tags.ol(*items)

    @render.ui
    def inv_why():
        r = row()
        if r is None:
            return ui.p("—")
        alert_id = f"AHR-{r['country']}-{r['disease']}-{r['as_of_date']}"
        explanation = data.explanation_for(alert_id)
        if not explanation:
            return ui.div(
                ui.p("No stored explanation artefact for this exact alert id."),
                ui.p(
                    f"Alert level is {r['alert_level']} with early-warning probability "
                    f"{r['early_warning_probability']:.0%} and reporting gap {r['reporting_gap']:.0%}. "
                    "Use contributions / counterfactuals when available, or Methodology for model families.",
                    class_="small text-muted mb-0",
                ),
            )
        return ui.div(
            ui.h5(explanation.get("headline", ""), class_="h6"),
            ui.p(explanation.get("narrative", "")),
            ui.p(f"Method: {explanation.get('method', '')}", class_="small text-muted mb-0"),
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
            return ui.p(
                "No counterfactual ablations stored for this case. "
                "When present, they show how the early-warning probability changes if a signal family is removed.",
                class_="text-muted mb-0",
            )
        blocks = [
            ui.p(
                "Each line: probability with the family → without it. "
                "A large drop means that family was material to the alert.",
                class_="small text-muted",
            )
        ]
        for item in items[:6]:
            blocks.append(
                ui.p(
                    ui.tags.strong(f"{item.get('family')}: "),
                    f"{item.get('probability_with', 0):.0%} → "
                    f"{item.get('probability_without', 0):.0%} ",
                    ui.tags.span(f"({item.get('interpretation', '')})", class_="text-muted"),
                    class_="mb-1",
                )
            )
        return ui.div(*blocks)

    @render.data_frame
    def inv_evidence():
        import pandas as pd

        r = row()
        if r is None:
            return render.DataGrid(pd.DataFrame({"note": ["—"]}))
        alert_id = f"AHR-{r['country']}-{r['disease']}-{r['as_of_date']}"
        explanation = data.explanation_for(alert_id) or {}
        rows = explanation.get("top_contributions") or []
        frame = pd.DataFrame(rows)
        if frame.empty:
            return render.DataGrid(pd.DataFrame({
                "note": ["No contribution rows stored for this alert — see Methodology for feature families."]
            }))
        keep = [c for c in ("feature", "family", "value", "contribution", "direction") if c in frame.columns]
        view = frame[keep].rename(columns={
            "feature": "Feature",
            "family": "Evidence family",
            "value": "Value",
            "contribution": "Contribution",
            "direction": "Direction",
        })
        return render.DataGrid(view, height="280px")

    @render.ui
    def inv_media_headlines():
        country = selected_country(input)
        disease = case_disease(input)
        as_of = selected_as_of(input)
        headlines = data.media_headlines_for_entity(country, disease, as_of, limit=15)
        if headlines.empty:
            return ui.p(
                "No media/intelligence headlines found for this country × disease under the as-of. "
                "That can mean sparse coverage, or that raw PADI/BEACON/EIOS panels are not on disk.",
                class_="small text-muted",
            )
        items = []
        for _, row in headlines.iterrows():
            title = str(row["headline"])
            meta = f"{row['published']} · {row['source']}"
            outlet = str(row.get("outlet") or "").strip()
            if outlet and outlet != row["source"]:
                meta = f"{meta} · {outlet}"
            url = str(row.get("url") or "").strip()
            if url:
                items.append(
                    ui.tags.li(
                        ui.tags.a(title, href=url, target="_blank", rel="noopener noreferrer"),
                        ui.tags.span(f" — {meta}", class_="small text-muted"),
                    )
                )
            else:
                items.append(
                    ui.tags.li(
                        ui.tags.strong(title),
                        ui.tags.span(f" — {meta}", class_="small text-muted"),
                    )
                )
        return ui.tags.ul({"class": "mb-3"}, *items)

    @render.data_frame
    def inv_provenance():
        import pandas as pd

        frame = data.provenance_for_entity(
            selected_country(input), case_disease(input), selected_as_of(input)
        )
        if frame.empty or (len(frame.columns) == 1 and "note" in frame.columns):
            return render.DataGrid(pd.DataFrame({
                "note": ["No provenance rows under this as-of for the selected case."]
            }))
        view = frame.rename(columns={
            "source_name": "Source",
            "record_id": "Record",
            "source_type": "Type",
            "source_tier": "Tier",
            "evidence_cluster": "Cluster",
            "published_at": "Published",
            "available_from": "Knowable from",
            "url": "URL",
            "notes": "Notes / excerpt",
            "realism": "Realism",
            "reliability": "Reliability",
        })
        return render.DataGrid(view, height="280px")
