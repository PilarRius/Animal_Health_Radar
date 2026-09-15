"""Application shell layout — shared as-of / disease across screens."""

from __future__ import annotations

from shiny import ui

from dashboard.data_loader import AppData


def app_ui(data: AppData):
    disease_choices = {"ALL": "All diseases", **{k: v.name for k, v in data.diseases.items()}}
    disease_only = {k: v.name for k, v in data.diseases.items()}
    as_of_choices = {d: d for d in data.as_of_dates}
    default_as_of = data.as_of_dates[-1] if data.as_of_dates else None
    country_choices = {iso: spec.name for iso, spec in data.countries.items()}

    global_filters = ui.div(
        ui.layout_columns(
            ui.input_select("as_of", "As-of date (global knowledge cut-off)", as_of_choices, selected=default_as_of),
            ui.input_select("disease", "Disease", disease_choices, selected="HPAI"),
            col_widths=(6, 6),
        ),
        ui.p(
            "All screens respect this as-of date. Nothing published after it enters MODEL ESTIMATES.",
            class_="small text-muted mb-2",
        ),
        class_="px-3 pt-2",
    )

    return ui.page_navbar(
        ui.nav_panel(
            "Global Radar",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.h4("Map"),
                    ui.input_select(
                        "map_layer",
                        "Layer",
                        {
                            "investigation_priority": "Investigation priority",
                            "early_warning_probability": "Early warning",
                            "latent_mean": "Latent activity",
                            "reporting_gap": "Reporting gap",
                            "forecast_14d": "Forecast 14d",
                            "forecast_28d": "Forecast 28d",
                            "environmental_signal": "Environmental signal",
                            "intelligence_signal": "Intelligence signal",
                        },
                    ),
                    ui.hr(),
                    ui.input_select("radar_country", "Country to investigate", country_choices, selected="POL"),
                    ui.input_action_button("go_investigate", "Open in Investigate", class_="btn-primary"),
                    ui.p(
                        "Select a country then open Investigate. Map colours are MODEL ESTIMATES, not confirmed outbreaks.",
                        class_="text-muted small",
                    ),
                    width=280,
                ),
                ui.div(ui.output_text("banner"), class_="alert alert-warning py-2"),
                ui.output_ui("radar_kpis"),
                ui.output_ui("radar_map"),
                ui.output_data_frame("radar_table"),
            ),
        ),
        ui.nav_panel(
            "Investigate",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_select("inv_country", "Country", country_choices, selected="POL"),
                    ui.input_select("inv_disease", "Disease", disease_only, selected="ASF"),
                    ui.p("As-of and (optional) disease filter follow the global controls above.", class_="small text-muted"),
                    width=280,
                ),
                ui.output_ui("inv_header"),
                ui.output_ui("inv_kpis"),
                ui.output_ui("inv_timeseries"),
                ui.card(ui.card_header("Evidence timeline"), ui.output_ui("inv_timeline")),
                ui.layout_columns(
                    ui.card(ui.card_header("Why this alert?"), ui.output_ui("inv_why")),
                    ui.card(ui.card_header("Counterfactuals"), ui.output_ui("inv_counterfactuals")),
                    col_widths=(6, 6),
                ),
                ui.card(ui.card_header("Evidence contributions"), ui.output_data_frame("inv_evidence")),
                ui.card(ui.card_header("Source provenance"), ui.output_data_frame("inv_provenance")),
            ),
        ),
        ui.nav_panel(
            "Forecast & Replay",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_select("fc_country", "Country", country_choices, selected="POL"),
                    ui.input_select("fc_disease", "Disease", disease_only, selected="ASF"),
                    ui.input_radio_buttons(
                        "fc_horizon",
                        "Horizon",
                        {"7": "7 days", "14": "14 days", "28": "28 days"},
                        selected="14",
                    ),
                    ui.p("Replay uses the global as-of as Day 0 knowledge cut-off.", class_="small text-muted"),
                    width=280,
                ),
                ui.output_ui("fc_summary"),
                ui.output_ui("fc_fan"),
                ui.card(
                    ui.card_header("Historical replay (what was knowable then)"),
                    ui.output_ui("fc_replay_summary"),
                    ui.output_data_frame("fc_replay_table"),
                ),
            ),
        ),
        title="Animal Health Radar",
        id="main_nav",
        fillable=True,
        header=global_filters,
        footer=ui.div(
            f"Animal Health Radar · data_mode={data.data_mode} · "
            "Probabilistic evidence-fusion under incomplete surveillance · MODEL ESTIMATES only",
            class_="text-center text-muted small py-2",
        ),
    )
