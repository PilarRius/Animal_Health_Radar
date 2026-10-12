"""Global Radar screen."""

from __future__ import annotations

import plotly.express as px
from shiny import reactive, render, ui

from dashboard.filter_state import selected_as_of

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

# Absolute colour ranges so the map matches KPI thresholds (not min–max of the slice).
LAYER_COLOR_RANGE = {
    "investigation_priority": (0.0, 1.0),
    "early_warning_probability": (0.0, 1.0),
    "reporting_gap": (0.0, 1.0),
    "environmental_signal": (0.0, 1.0),
    "intelligence_signal": (0.0, 1.0),
}

# From config/thresholds.yaml investigation_priority.bands
PRIORITY_MODERATE = 0.30
PRIORITY_HIGH = 0.52

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


def _kpi(value: str, label: str, hint: str) -> ui.Tag:
    return ui.div(
        {"class": "ahr-kpi"},
        ui.div({"class": "ahr-kpi-value"}, value),
        ui.div({"class": "ahr-kpi-label"}, label),
        ui.div({"class": "ahr-kpi-hint"}, hint),
    )


def _attention_rows(frame, data):  # noqa: ANN001
    hit = frame.loc[frame["alert_level"].isin(["WATCH", "ALERT", "CRITICAL"])].copy()
    if hit.empty:
        return hit
    level_order = {"CRITICAL": 0, "ALERT": 1, "WATCH": 2}
    hit["_ord"] = hit["alert_level"].map(level_order).fillna(9)
    hit = hit.sort_values(["_ord", "investigation_priority"], ascending=[True, False])
    return hit


def register(input, output, session, data, filtered_predictions):  # noqa: ANN001
    show_attention = reactive.Value(False)

    @reactive.effect
    @reactive.event(input.show_attention_countries)
    def _toggle_attention():
        show_attention.set(not show_attention())

    @reactive.effect
    @reactive.event(input.as_of_radar, input.disease_radar, input.main_nav)
    def _hide_attention_on_filter_change():
        show_attention.set(False)

    @render.ui
    def radar_kpis():
        frame = filtered_predictions()
        if frame.empty:
            return ui.p("No predictions for this as-of / disease. Try another as-of or disease filter.")
        n_elevated = int((frame["investigation_priority"] >= PRIORITY_MODERATE).sum())
        n_high = int((frame["investigation_priority"] >= PRIORITY_HIGH).sum())
        n_attention = int(frame["alert_level"].isin(["WATCH", "ALERT", "CRITICAL"]).sum())
        mean_gap = float(frame["reporting_gap"].mean())
        open_hint = "click to hide list" if show_attention() else "click to see countries"
        attention_btn = ui.input_action_button(
            "show_attention_countries",
            ui.div(
                ui.div({"class": "ahr-kpi-value"}, str(n_attention)),
                ui.div({"class": "ahr-kpi-label"}, "Need analyst attention"),
                ui.div({"class": "ahr-kpi-hint"}, f"WATCH / ALERT / CRITICAL · {open_hint}"),
            ),
            class_="ahr-kpi-btn",
        )
        return ui.div(
            {"class": "ahr-kpi-row"},
            _kpi(str(len(frame)), "Places scored", "country × disease rows"),
            attention_btn,
            _kpi(
                str(n_elevated),
                "Elevated priority",
                f"≥ {PRIORITY_MODERATE:.2f} moderate · {n_high} high (≥ {PRIORITY_HIGH:.2f})",
            ),
            _kpi(f"{mean_gap:.0%}", "Mean reporting gap", "avg latent above observed"),
        )

    @render.ui
    def radar_attention_detail():
        if not show_attention():
            return ui.div()
        frame = filtered_predictions()
        hit = _attention_rows(frame, data)
        if hit.empty:
            return ui.div(
                {"class": "ahr-attention-detail"},
                ui.h6("Need analyst attention"),
                ui.p("No countries at WATCH / ALERT / CRITICAL for this filter.", class_="mb-0 small text-muted"),
            )
        items = []
        for _, row in hit.iterrows():
            iso = str(row["country"])
            spec = data.countries.get(iso)
            name = spec.name if spec is not None else iso
            disease = str(row["disease"])
            level = str(row["alert_level"])
            priority = float(row["investigation_priority"])
            items.append(
                ui.tags.li(
                    ui.tags.strong(f"{name} ({iso})"),
                    f" · {disease} · {level} · priority {priority:.2f}",
                )
            )
        return ui.div(
            {"class": "ahr-attention-detail"},
            ui.h6(f"Need analyst attention — {len(items)} place(s)"),
            ui.tags.ul(*items),
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
        # One row per country for the choropleth (keep highest priority when disease=ALL).
        if plot_df["country"].duplicated().any():
            plot_df = (
                plot_df.sort_values("investigation_priority", ascending=False)
                .drop_duplicates("country", keep="first")
            )
        title = LAYER_TITLES.get(layer, layer.replace("_", " ").title())
        range_color = LAYER_COLOR_RANGE.get(layer)
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
                "investigation_priority": ":.2f",
            },
            color_continuous_scale="YlOrRd",
            range_color=range_color,
            projection="natural earth",
            title=f"{title} · as-of {selected_as_of(input)} · MODEL ESTIMATE",
        )
        colorbar = dict(title="")
        if layer == "investigation_priority":
            colorbar = dict(
                title="",
                tickmode="array",
                tickvals=[0.0, PRIORITY_MODERATE, PRIORITY_HIGH, 0.72, 1.0],
                ticktext=["0", "mod 0.30", "high 0.52", "v.high", "1"],
            )
        fig.update_layout(
            margin=dict(l=0, r=0, t=48, b=0),
            height=520,
            paper_bgcolor="#0b1220",
            plot_bgcolor="#0b1220",
            font_color="#e5e9f0",
            geo=dict(bgcolor="#0b1220", lakecolor="#0b1220", landcolor="#1c2434"),
            coloraxis_colorbar=colorbar,
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
