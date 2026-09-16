"""Application shell — Intro first, then analysis, then Data Sources & Methodology."""

from __future__ import annotations

from shiny import ui

from dashboard.content import (
    analysis_guide_strip,
    data_sources_panel,
    intro_panel,
    methodology_panel,
)
from dashboard.data_loader import AppData


def _ahr_css() -> ui.Tag:
    return ui.tags.style(
        """
        .ahr-hero {
          background: linear-gradient(135deg, #0b1220 0%, #1a2a3a 55%, #243447 100%);
          border: 1px solid #3b4a5a;
          color: #eceff4;
        }
        .ahr-hero h2 { color: #eceff4; letter-spacing: 0.02em; }
        .ahr-flow {
          background: #121a2b;
          border: 1px dashed #5e81ac;
          color: #d8dee9;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.95rem;
        }
        .ahr-prose { max-width: 1100px; margin: 0 auto; color: #e5e9f0; }
        .ahr-prose h2, .ahr-prose h4 { color: #eceff4; }
        .ahr-prose .card {
          background: #121a2b;
          border-color: #3b4a5a;
          color: #e5e9f0;
        }
        .ahr-prose .card-header {
          background: #1c2434;
          border-bottom-color: #3b4a5a;
          font-weight: 600;
        }
        .ahr-guide {
          background: #1c2434;
          border: 1px solid #3b4a5a;
          color: #d8dee9;
        }
        .navbar { border-bottom: 1px solid #3b4a5a; }
        """
    )


def app_ui(data: AppData):
    disease_choices = {"ALL": "All diseases", **{k: v.name for k, v in data.diseases.items()}}
    disease_only = {k: v.name for k, v in data.diseases.items()}
    as_of_choices = {d: d for d in data.as_of_dates}
    default_as_of = data.as_of_dates[-1] if data.as_of_dates else None
    country_choices = {iso: spec.name for iso, spec in data.countries.items()}

    global_filters = ui.div(
        ui.layout_columns(
            ui.input_select(
                "as_of",
                "As-of date (knowledge cut-off for all analysis tabs)",
                as_of_choices,
                selected=default_as_of,
            ),
            ui.input_select("disease", "Disease (Radar filter)", disease_choices, selected="HPAI"),
            col_widths=(6, 6),
        ),
        ui.p(
            "Applies to Global Radar / Investigate / Forecast. Intro & docs tabs ignore the map filter.",
            class_="small text-muted mb-2",
        ),
        class_="px-3 pt-2",
    )

    return ui.page_navbar(
        ui.nav_panel("Intro", intro_panel(data)),
        ui.nav_panel(
            "Global Radar",
            analysis_guide_strip(),
            ui.layout_sidebar(
                ui.sidebar(
                    ui.h4("Map"),
                    ui.input_select(
                        "map_layer",
                        "Layer",
                        {
                            "investigation_priority": "Investigation priority (start here)",
                            "early_warning_probability": "Early warning probability",
                            "latent_mean": "Estimated latent activity",
                            "reporting_gap": "Estimated reporting gap",
                            "forecast_14d": "Forecast 14d",
                            "forecast_28d": "Forecast 28d",
                            "environmental_signal": "Environmental signal",
                            "intelligence_signal": "Intelligence signal",
                        },
                    ),
                    ui.hr(),
                    ui.input_select(
                        "radar_country",
                        "Country to investigate",
                        country_choices,
                        selected="POL",
                    ),
                    ui.input_action_button(
                        "go_investigate",
                        "Open in Investigate →",
                        class_="btn-primary",
                    ),
                    ui.p(
                        "Colours are MODEL ESTIMATES of investigation priority — "
                        "not confirmed outbreak counts.",
                        class_="text-muted small",
                    ),
                    width=300,
                ),
                ui.div(ui.output_text("banner"), class_="alert alert-warning py-2"),
                ui.output_ui("radar_kpis"),
                ui.output_ui("radar_map"),
                ui.card(
                    ui.card_header("Country table (sorted by investigation priority)"),
                    ui.output_data_frame("radar_table"),
                ),
            ),
        ),
        ui.nav_panel(
            "Investigate",
            analysis_guide_strip(),
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_select("inv_country", "Country", country_choices, selected="POL"),
                    ui.input_select("inv_disease", "Disease", disease_only, selected="ASF"),
                    ui.p(
                        "Compare official observed burden vs estimated latent activity at the global as-of.",
                        class_="small text-muted",
                    ),
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
                ui.card(
                    ui.card_header("Evidence contributions"),
                    ui.output_data_frame("inv_evidence"),
                ),
                ui.card(
                    ui.card_header("Source provenance"),
                    ui.output_data_frame("inv_provenance"),
                ),
            ),
        ),
        ui.nav_panel(
            "Forecast & Replay",
            analysis_guide_strip(),
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
                    ui.p(
                        "Replay uses the global as-of as Day 0. Rows after as-of are outcomes, not inputs.",
                        class_="small text-muted",
                    ),
                    width=280,
                ),
                ui.output_ui("fc_summary"),
                ui.output_ui("fc_fan"),
                ui.card(
                    ui.card_header("Historical replay — what was knowable then?"),
                    ui.output_ui("fc_replay_summary"),
                    ui.output_data_frame("fc_replay_table"),
                ),
            ),
        ),
        ui.nav_panel("Data sources", data_sources_panel(data)),
        ui.nav_panel("Methodology", methodology_panel(data)),
        title="Animal Health Radar",
        id="main_nav",
        fillable=True,
        header=ui.TagList(_ahr_css(), global_filters),
        footer=ui.div(
            f"Animal Health Radar · WOAH Datathon 2026 Challenge 1 · data_mode={data.data_mode} · "
            "MODEL ESTIMATES only — not confirmed outbreaks",
            class_="text-center text-muted small py-2",
        ),
    )
