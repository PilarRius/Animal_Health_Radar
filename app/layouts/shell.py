"""Application shell layout."""

from __future__ import annotations

from shiny import ui

from app.data_loader import AppData


def app_ui(data: AppData):
    disease_choices = {"ALL": "All diseases", **{k: v.name for k, v in data.diseases.items()}}
    as_of_choices = {d: d for d in data.as_of_dates}
    default_as_of = data.as_of_dates[-1] if data.as_of_dates else None
    country_choices = {iso: spec.name for iso, spec in data.countries.items()}

    return ui.page_navbar(
        ui.nav_panel(
            "Global Radar",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.h4("Filters"),
                    ui.input_select("disease", "Disease", disease_choices, selected="HPAI"),
                    ui.input_select("as_of", "As-of date", as_of_choices, selected=default_as_of),
                    ui.input_select(
                        "map_layer",
                        "Map layer",
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
                    ui.p(
                        "Choropleth shows MODEL ESTIMATES under the selected as-of "
                        "cut-off. No information published after as-of is used.",
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
                    ui.input_select(
                        "inv_disease",
                        "Disease",
                        {k: v.name for k, v in data.diseases.items()},
                        selected="ASF",
                    ),
                    ui.input_select("as_of_inv", "As-of date", as_of_choices, selected=default_as_of),
                    width=280,
                ),
                ui.output_ui("inv_header"),
                ui.output_ui("inv_kpis"),
                ui.output_ui("inv_timeseries"),
                ui.layout_columns(
                    ui.card(ui.card_header("Why this alert?"), ui.output_ui("inv_why")),
                    ui.card(ui.card_header("Counterfactuals"), ui.output_ui("inv_counterfactuals")),
                    col_widths=(6, 6),
                ),
                ui.card(ui.card_header("Evidence contributions"), ui.output_data_frame("inv_evidence")),
            ),
        ),
        ui.nav_panel(
            "Forecast & Replay",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_select("fc_country", "Country", country_choices, selected="POL"),
                    ui.input_select(
                        "fc_disease",
                        "Disease",
                        {k: v.name for k, v in data.diseases.items()},
                        selected="ASF",
                    ),
                    ui.input_select("fc_as_of", "As-of / replay date", as_of_choices, selected=default_as_of),
                    ui.input_radio_buttons(
                        "fc_horizon",
                        "Horizon",
                        {"7": "7 days", "14": "14 days", "28": "28 days"},
                        selected="14",
                    ),
                    width=280,
                ),
                ui.output_ui("fc_summary"),
                ui.output_ui("fc_fan"),
                ui.card(
                    ui.card_header("Historical replay"),
                    ui.p(
                        "Selecting an as-of date reconstructs what the system would have known then. "
                        "Later as-of rows show subsequent model states and outcomes on the synthetic corpus.",
                        class_="small text-muted",
                    ),
                    ui.output_data_frame("fc_replay_table"),
                ),
            ),
        ),
        title="Animal Health Radar",
        id="main_nav",
        fillable=True,
        footer=ui.div(
            f"Animal Health Radar · data_mode={data.data_mode} · "
            "Probabilistic evidence-fusion under incomplete surveillance",
            class_="text-center text-muted small py-2",
        ),
    )
