"""Application shell — shared top filters; tab-specific controls only when needed."""

from __future__ import annotations

from shiny import ui

from dashboard.content import (
    data_sources_panel,
    intro_panel,
    methodology_panel,
    section_note,
    tab_explainer,
)
from dashboard.data_loader import AppData

LAYER_HELP = ui.tags.ul(
    {"class": "small mb-0 ahr-layer-help"},
    ui.tags.li(ui.tags.strong("Investigation priority — "), "Start here. Composite triage score for where an analyst should look first."),
    ui.tags.li(ui.tags.strong("Early warning probability — "), "Calibrated chance of rising official visibility in ~28 days."),
    ui.tags.li(ui.tags.strong("Estimated latent activity — "), "Model nowcast of underlying burden (not confirmed cases)."),
    ui.tags.li(ui.tags.strong("Reporting gap — "), "How much larger the latent estimate is than official observation."),
    ui.tags.li(ui.tags.strong("Forecast 14d / 28d — "), "Short-term expected burden trajectories."),
    ui.tags.li(ui.tags.strong("Environmental / Intelligence signal — "), "Context layers that feed the model (not standalone alerts)."),
)


def _ahr_css() -> ui.Tag:
    return ui.tags.style(
        """
        .ahr-hero {
          background: linear-gradient(135deg, #0b1220 0%, #1a2a3a 55%, #243447 100%);
          border: 1px solid #3b4a5a;
          color: #eceff4;
        }
        .ahr-hero h2 { color: #eceff4; letter-spacing: 0.02em; }
        .ahr-hero h4 { color: #ffffff !important; opacity: 1; }
        .ahr-flow {
          background: #121a2b;
          border: 1px dashed #5e81ac;
          color: #d8dee9;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.95rem;
        }
        .ahr-prose { max-width: 1100px; margin: 0 auto; color: #1f2937; }
        .ahr-prose h2, .ahr-prose h4 { color: #0f172a; }
        .ahr-prose p, .ahr-prose li, .ahr-prose ul { color: #1f2937; }
        .ahr-prose .text-muted { color: #4b5563 !important; }
        .ahr-prose .card {
          background: #121a2b;
          border-color: #3b4a5a;
          color: #e5e9f0;
        }
        .ahr-prose .card p, .ahr-prose .card li, .ahr-prose .card strong {
          color: #e5e9f0;
        }
        .ahr-prose .card-header {
          background: #1c2434;
          border-bottom-color: #3b4a5a;
          color: #eceff4;
          font-weight: 600;
        }
        .ahr-callout {
          background: #eef2ff;
          border: 1px solid #c7d2fe;
          border-radius: 0.5rem;
          color: #1e3a5f;
          padding: 1rem 1.25rem;
          margin-bottom: 1rem;
        }
        .ahr-callout h4 { color: #1e3a5f !important; margin-top: 0; }
        .ahr-callout p, .ahr-callout li { color: #1e3a5f !important; }
        .ahr-explain {
          background: #f8fafc;
          border: 1px solid #cbd5e1;
          border-left: 4px solid #2563eb;
          border-radius: 0.5rem;
          padding: 0.85rem 1rem;
          color: #0f172a;
        }
        .ahr-explain-q {
          margin-bottom: 0.65rem;
          color: #0f172a;
        }
        .ahr-explain strong { color: #0f172a; }
        .ahr-explain p { color: #334155 !important; }
        .ahr-section-note {
          background: #fffbeb;
          border: 1px solid #fde68a;
          border-radius: 0.4rem;
          padding: 0.55rem 0.8rem;
          color: #78350f;
        }
        .ahr-layer-help { padding-left: 1.1rem; color: #475569; }
        .ahr-layer-help li { margin-bottom: 0.35rem; }
        .navbar { border-bottom: 1px solid #3b4a5a; }
        .ahr-tab-body { padding: 0 0.25rem 1rem; }
        .ahr-global-filters {
          background: #f8fafc;
          border-bottom: 1px solid #e2e8f0;
          padding-bottom: 0.5rem;
        }
        .ahr-filter-row {
          display: flex;
          flex-wrap: wrap;
          gap: 0.75rem 1rem;
          align-items: flex-end;
        }
        .ahr-filter-item {
          flex: 1 1 200px;
          min-width: 180px;
        }
        """
    )


def app_ui(data: AppData):
    disease_choices = {"ALL": "All diseases (Radar overview)", **{k: v.name for k, v in data.diseases.items()}}
    as_of_choices = {d: d for d in data.as_of_dates}
    default_as_of = data.as_of_dates[-1] if data.as_of_dates else None
    country_choices = {iso: spec.name for iso, spec in data.countries.items()}
    default_country = "POL" if "POL" in country_choices else next(iter(country_choices), None)

    # Filters live in the page header but are shown only on analysis tabs.
    # Country is hidden on Global Radar (map/table triage only).
    analysis_tabs = (
        "input.main_nav === 'Global Radar' || "
        "input.main_nav === 'Investigate' || "
        "input.main_nav === 'Forecast & Replay'"
    )
    case_tabs = (
        "input.main_nav === 'Investigate' || "
        "input.main_nav === 'Forecast & Replay'"
    )

    global_filters = ui.panel_conditional(
        analysis_tabs,
        ui.div(
            {"class": "ahr-global-filters px-3 pt-2"},
            ui.div(
                {"class": "ahr-filter-row"},
                ui.div(
                    {"class": "ahr-filter-item"},
                    ui.input_select(
                        "as_of",
                        "As-of date (knowledge cut-off)",
                        as_of_choices,
                        selected=default_as_of,
                    ),
                ),
                ui.div(
                    {"class": "ahr-filter-item"},
                    ui.input_select(
                        "disease",
                        "Disease",
                        disease_choices,
                        selected="HPAI",
                    ),
                ),
                ui.panel_conditional(
                    case_tabs,
                    ui.div(
                        {"class": "ahr-filter-item"},
                        ui.input_select(
                            "country",
                            "Country",
                            country_choices,
                            selected=default_country,
                        ),
                    ),
                ),
            ),
            ui.panel_conditional(
                "input.main_nav === 'Global Radar'",
                ui.p(
                    "As-of and disease filter the map and priority queue. "
                    "Country is selected on Investigate / Forecast.",
                    class_="small text-muted mb-0",
                ),
            ),
            ui.panel_conditional(
                case_tabs,
                ui.p(
                    "As-of, disease, and country apply to this case view. "
                    "If Disease is “All”, Investigate/Forecast use HPAI.",
                    class_="small text-muted mb-0",
                ),
            ),
        ),
    )

    return ui.page_navbar(
        ui.nav_panel("Intro", intro_panel(data)),
        ui.nav_panel(
            "Global Radar",
            ui.div(
                {"class": "ahr-tab-body px-3 pt-2"},
                tab_explainer(
                    question="Where should an epidemiologist look first this week?",
                    what="A triage map and ranked country table built from MODEL ESTIMATES "
                    "(investigation priority, early-warning probability, latent activity, reporting gap).",
                    how="1) Keep Investigation priority as the default layer. "
                    "2) Use as-of / disease above the map. "
                    "3) Note a top country in the priority queue, then open Investigate and select it there.",
                    remember="Colours are not confirmed outbreak counts. Darker = higher estimated need to look — not proof of infection.",
                ),
                ui.layout_sidebar(
                    ui.sidebar(
                        ui.h5("Map only"),
                        ui.input_select(
                            "map_layer",
                            "Colour the map by",
                            {
                                "investigation_priority": "Investigation priority (start here)",
                                "early_warning_probability": "Early warning probability",
                                "latent_mean": "Estimated latent activity",
                                "reporting_gap": "Estimated reporting gap",
                                "forecast_14d": "Forecast · 14 days",
                                "forecast_28d": "Forecast · 28 days",
                                "environmental_signal": "Environmental context signal",
                                "intelligence_signal": "Intelligence context signal",
                            },
                        ),
                        ui.p("Layer guide", class_="fw-semibold small mb-1 mt-2"),
                        LAYER_HELP,
                        ui.hr(),
                        ui.p(
                            "Country is chosen on Investigate / Forecast only. "
                            "After you spot a priority country here, switch tabs and select it there.",
                            class_="text-muted small mb-0",
                        ),
                        width=320,
                    ),
                    ui.div(ui.output_text("banner"), class_="alert alert-warning py-2"),
                    section_note(
                        "Summary strip",
                        "How many places look elevated right now under the current as-of and disease filter.",
                    ),
                    ui.output_ui("radar_kpis"),
                    section_note(
                        "Map",
                        "Choropleth of the selected layer. Hover a country for latent vs observed, gap, and alert level.",
                    ),
                    ui.output_ui("radar_map"),
                    ui.card(
                        ui.card_header("Priority queue — countries sorted for investigation"),
                        section_note(
                            "How to read the table",
                            "Top rows = highest investigation priority. Open Investigate and select that country there.",
                        ),
                        ui.output_data_frame("radar_table"),
                    ),
                ),
            ),
        ),
        ui.nav_panel(
            "Investigate",
            ui.div(
                {"class": "ahr-tab-body px-3 pt-2"},
                tab_explainer(
                    question="For this country × disease, what is officially visible versus what we estimate is happening — and why?",
                    what="A case file: KPIs, latent-vs-observed time series, evidence timeline, “why this alert”, "
                    "counterfactual ablations, feature contributions, and provenance.",
                    how="1) Set Country, Disease, and As-of above. "
                    "2) Compare Observed vs Estimated latent and the Reporting gap. "
                    "3) Read Why this alert + Counterfactuals before acting on a score.",
                    remember="This is epidemic intelligence support, not a confirmation of outbreak. Official verification still decides response.",
                ),
                ui.layout_sidebar(
                    ui.sidebar(
                        ui.h5("This case"),
                        ui.p(
                            "Uses Country, Disease, and As-of from the filter bar above. "
                            "No duplicated filters in this sidebar.",
                            class_="small text-muted",
                        ),
                        ui.hr(),
                        ui.p(ui.tags.strong("Reading order"), class_="small mb-1"),
                        ui.tags.ol(
                            {"class": "small mb-0"},
                            ui.tags.li("KPIs (gap & early-warning)"),
                            ui.tags.li("Latent vs observed chart"),
                            ui.tags.li("Why this alert"),
                            ui.tags.li("Counterfactuals & contributions"),
                            ui.tags.li("Provenance"),
                        ),
                        width=280,
                    ),
                    ui.output_ui("inv_header"),
                    section_note(
                        "Case snapshot",
                        "Observed = official visible burden. Latent = estimated underlying activity. Gap = how much may still be unseen.",
                    ),
                    ui.output_ui("inv_kpis"),
                    section_note(
                        "Nowcast view",
                        "Solid red = estimated latent mean; band = uncertainty; blue = official observed. "
                        "Dashed line = current as-of cut-off.",
                    ),
                    ui.output_ui("inv_timeseries"),
                    ui.card(
                        ui.card_header("Evidence timeline — what became knowable, and when"),
                        section_note(
                            "Purpose",
                            "Chronology of intelligence/official signals available under the as-of (not a clinical case history).",
                        ),
                        ui.output_ui("inv_timeline"),
                    ),
                    ui.layout_columns(
                        ui.card(
                            ui.card_header("Why this alert?"),
                            section_note(
                                "Purpose",
                                "Plain-language rationale for the current alert state, grounded in model artefacts.",
                            ),
                            ui.output_ui("inv_why"),
                        ),
                        ui.card(
                            ui.card_header("Counterfactuals — what if we remove a signal family?"),
                            section_note(
                                "Purpose",
                                "If probability collapses after removing intelligence or environment, that family was material to the alert.",
                            ),
                            ui.output_ui("inv_counterfactuals"),
                        ),
                        col_widths=(6, 6),
                    ),
                    ui.card(
                        ui.card_header("Evidence contributions — which features pushed the score?"),
                        ui.output_data_frame("inv_evidence"),
                    ),
                    ui.card(
                        ui.card_header("Source provenance — who said what, and when was it knowable?"),
                        ui.output_data_frame("inv_provenance"),
                    ),
                ),
            ),
        ),
        ui.nav_panel(
            "Forecast & Replay",
            ui.div(
                {"class": "ahr-tab-body px-3 pt-2"},
                tab_explainer(
                    question="What is likely next — and how early would we have seen concern if we froze knowledge on a past date?",
                    what="Two tools in one tab: (A) short-term probabilistic forecast fans (7/14/28 days), "
                    "and (B) historical replay of what the model knew at the selected as-of, with lead-time against later official outcomes.",
                    how="1) Set Country / Disease / As-of above. "
                    "2) Choose the horizon here. "
                    "3) Read the forecast summary + fan chart, then Replay for lead time.",
                    remember="Forecasts are distributions with uncertainty, not single certainties. Replay outcomes after as-of are labels for evaluation.",
                ),
                ui.layout_sidebar(
                    ui.sidebar(
                        ui.h5("Horizon only"),
                        ui.input_radio_buttons(
                            "fc_horizon",
                            "Primary horizon for the summary cards",
                            {"7": "7 days", "14": "14 days", "28": "28 days"},
                            selected="14",
                        ),
                        ui.p(
                            "Country, disease, and as-of come from the filter bar above. "
                            "Replay uses that as-of as Day 0; later rows are evaluation outcomes only.",
                            class_="small text-muted mb-0",
                        ),
                        width=280,
                    ),
                    section_note(
                        "A · Short-term forecast",
                        "Median and interval for the selected horizon, plus chance of increase / new official visibility.",
                    ),
                    ui.output_ui("fc_summary"),
                    section_note(
                        "Fan chart",
                        "Coloured lines = 7/14/28-day forecasts over successive as-of weeks. "
                        "Dotted white = official observed. Green dashed = current as-of.",
                    ),
                    ui.output_ui("fc_fan"),
                    ui.card(
                        ui.card_header("B · Historical replay — what was knowable then?"),
                        section_note(
                            "Purpose",
                            "Demonstrate lead time: would the model have raised concern before official burden rose? "
                            "This is the Challenge 1 early-warning proof.",
                        ),
                        ui.output_ui("fc_replay_summary"),
                        ui.output_data_frame("fc_replay_table"),
                    ),
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
