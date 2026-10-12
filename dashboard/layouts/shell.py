"""Application shell — WOAH-inspired header + rounded tabs; filters live in each analysis sidebar."""

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
        @import url("https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap");

        :root {
          --woah-blue: #004B87;
          --woah-blue-deep: #003466;
          --woah-blue-mid: #1A6BA8;
          --woah-sky: #E8F2FA;
          --woah-coral: #E4572E;
          --woah-coral-soft: #FDE8E1;
          --woah-sage: #2F7D6D;
          --woah-ink: #1C2B36;
          --woah-muted: #5C6B78;
          --woah-paper: #F5F8FB;
          --woah-line: #C5D6E4;
          --ahr-font: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
        }

        html, body {
          font-family: var(--ahr-font);
          color: var(--woah-ink);
          background:
            radial-gradient(1200px 500px at 10% -10%, rgba(26, 107, 168, 0.12), transparent 55%),
            radial-gradient(900px 420px at 100% 0%, rgba(228, 87, 46, 0.07), transparent 50%),
            var(--woah-paper);
          margin: 0;
        }

        .ahr-shell { min-height: 100vh; display: flex; flex-direction: column; }

        .ahr-header {
          background:
            linear-gradient(120deg, var(--woah-blue-deep) 0%, var(--woah-blue) 48%, var(--woah-blue-mid) 100%);
          color: #fff;
          padding: 1.25rem 1.5rem 1.1rem;
          position: relative;
          overflow: hidden;
        }
        .ahr-header::after {
          content: "";
          position: absolute;
          right: -40px;
          top: -60px;
          width: 280px;
          height: 280px;
          border-radius: 50%;
          background: radial-gradient(circle, rgba(228, 87, 46, 0.28) 0%, transparent 68%);
          pointer-events: none;
        }
        .ahr-header-inner {
          max-width: 1400px;
          margin: 0 auto;
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          gap: 1.25rem;
          flex-wrap: wrap;
          position: relative;
          z-index: 1;
        }
        .ahr-brand {
          font-size: 0.72rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          opacity: 0.88;
          font-weight: 600;
          margin: 0 0 0.35rem;
          color: #fff;
        }
        .ahr-title {
          font-size: clamp(1.45rem, 2.2vw, 1.85rem);
          font-weight: 700;
          margin: 0;
          letter-spacing: -0.02em;
          line-height: 1.15;
          color: #fff;
        }
        .ahr-subtitle {
          margin: 0.4rem 0 0;
          font-size: 0.95rem;
          opacity: 0.92;
          font-weight: 400;
          max-width: 36rem;
        }
        .ahr-header-meta {
          text-align: right;
          font-size: 0.8rem;
          line-height: 1.5;
        }
        .ahr-pill {
          display: inline-block;
          background: rgba(255, 255, 255, 0.14);
          border: 1px solid rgba(255, 255, 255, 0.22);
          border-radius: 999px;
          padding: 0.2rem 0.7rem;
          margin-bottom: 0.35rem;
          font-weight: 600;
          letter-spacing: 0.02em;
        }
        .ahr-accent-bar {
          height: 4px;
          background: linear-gradient(90deg, var(--woah-coral) 0%, #F0A28A 35%, var(--woah-sage) 100%);
        }

        .ahr-main {
          max-width: 1400px;
          width: 100%;
          margin: 0 auto;
          padding: 1.1rem 1.25rem 2.5rem;
          flex: 1;
        }

        /* Soft pill tabs — WOAH blues, coral active cue */
        .ahr-shell .nav-tabs {
          border-bottom: none;
          gap: 0.4rem;
          margin-bottom: 1.15rem;
          flex-wrap: wrap;
          padding: 0.35rem;
          background: rgba(255, 255, 255, 0.72);
          border: 1px solid var(--woah-line);
          border-radius: 16px;
          box-shadow: 0 1px 2px rgba(0, 52, 102, 0.04);
        }
        .ahr-shell .nav-tabs .nav-item { margin-bottom: 0; }
        .ahr-shell .nav-tabs .nav-link {
          border: 1px solid transparent;
          color: var(--woah-blue);
          font-weight: 600;
          font-size: 0.88rem;
          padding: 0.55rem 1.05rem;
          border-radius: 12px;
          background: transparent;
          transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
          white-space: nowrap;
        }
        .ahr-shell .nav-tabs .nav-link:hover {
          color: var(--woah-blue-deep);
          background: var(--woah-sky);
        }
        .ahr-shell .nav-tabs .nav-link.active {
          color: #fff;
          background: linear-gradient(145deg, var(--woah-blue) 0%, var(--woah-blue-mid) 100%);
          border-color: transparent;
          box-shadow: 0 4px 14px rgba(0, 75, 135, 0.28);
          position: relative;
        }
        .ahr-shell .nav-tabs .nav-link.active::after {
          content: "";
          position: absolute;
          left: 22%;
          right: 22%;
          bottom: 5px;
          height: 2px;
          border-radius: 2px;
          background: var(--woah-coral);
        }

        .ahr-hero {
          background: linear-gradient(135deg, var(--woah-blue-deep) 0%, var(--woah-blue) 55%, #1A6BA8 100%);
          border: none;
          color: #fff !important;
          border-radius: 14px;
        }
        .ahr-prose .ahr-hero h2,
        .ahr-prose .ahr-hero h4,
        .ahr-prose .ahr-hero p,
        .ahr-hero h2,
        .ahr-hero h4,
        .ahr-hero p {
          color: #ffffff !important;
          opacity: 1;
        }
        .ahr-hero h2 { letter-spacing: 0.02em; }
        .ahr-flow {
          background: rgba(0, 0, 0, 0.22);
          border: 1px dashed rgba(255, 255, 255, 0.35);
          color: #e8f2fa;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.95rem;
          border-radius: 8px;
        }
        .ahr-prose { max-width: 1100px; margin: 0 auto; color: var(--woah-ink); }
        .ahr-prose h2, .ahr-prose h4 { color: var(--woah-blue-deep); }
        .ahr-prose p, .ahr-prose li, .ahr-prose ul { color: var(--woah-ink); }
        .ahr-prose .text-muted { color: var(--woah-muted) !important; }
        .ahr-prose .card {
          background: #fff;
          border-color: var(--woah-line);
          color: var(--woah-ink);
          border-radius: 12px;
        }
        .ahr-prose .card p, .ahr-prose .card li, .ahr-prose .card strong { color: var(--woah-ink); }
        .ahr-prose .card-header {
          background: var(--woah-sky);
          border-bottom-color: var(--woah-line);
          color: var(--woah-blue-deep);
          font-weight: 600;
        }
        .ahr-callout {
          background: var(--woah-sky);
          border: 1px solid var(--woah-line);
          border-left: 4px solid var(--woah-blue);
          border-radius: 0.55rem;
          color: var(--woah-blue-deep);
          padding: 1rem 1.25rem;
          margin-bottom: 1rem;
        }
        .ahr-callout h4 { color: var(--woah-blue-deep) !important; margin-top: 0; }
        .ahr-callout p, .ahr-callout li { color: var(--woah-ink) !important; }
        .ahr-explain {
          background: #fff;
          border: 1px solid var(--woah-line);
          border-left: 4px solid var(--woah-coral);
          border-radius: 0.55rem;
          padding: 0.85rem 1rem;
          color: var(--woah-ink);
          box-shadow: 0 1px 2px rgba(0, 52, 102, 0.04);
        }
        .ahr-explain-q { margin-bottom: 0.65rem; color: var(--woah-blue-deep); }
        .ahr-explain strong { color: var(--woah-blue-deep); }
        .ahr-explain p { color: var(--woah-muted) !important; }
        .ahr-section-note {
          background: #fff;
          border: 1px solid var(--woah-line);
          border-left: 3px solid var(--woah-sage);
          border-radius: 0.4rem;
          padding: 0.55rem 0.8rem;
          color: var(--woah-ink);
        }
        .ahr-layer-help { padding-left: 1.1rem; color: var(--woah-muted); }
        .ahr-layer-help li { margin-bottom: 0.35rem; }
        .ahr-tab-body { padding: 0 0.05rem 1rem; }

        .ahr-sidebar-block {
          margin-bottom: 0.85rem;
        }
        .ahr-sidebar-label {
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--woah-blue);
          margin: 0 0 0.45rem;
        }
        .bslib-sidebar-layout > .sidebar {
          background: #fff !important;
          border-right: 1px solid var(--woah-line) !important;
        }
        .card {
          border-color: var(--woah-line);
          border-radius: 12px;
        }
        .card-header {
          background: var(--woah-sky);
          color: var(--woah-blue-deep);
          font-weight: 600;
        }

        /* Compact Radar KPI strip */
        .ahr-kpi-row {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 0.65rem;
          margin-bottom: 0.75rem;
        }
        @media (max-width: 900px) {
          .ahr-kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        .ahr-kpi {
          background: #fff;
          border: 1px solid var(--woah-line);
          border-radius: 10px;
          padding: 0.55rem 0.75rem 0.6rem;
          min-height: 0;
        }
        .ahr-kpi-value {
          font-size: 1.35rem;
          font-weight: 700;
          line-height: 1.15;
          color: var(--woah-blue-deep);
        }
        .ahr-kpi-label {
          font-size: 0.78rem;
          font-weight: 600;
          color: var(--woah-ink);
          margin-top: 0.15rem;
        }
        .ahr-kpi-hint {
          font-size: 0.7rem;
          color: var(--woah-muted);
          margin-top: 0.1rem;
        }
        button.ahr-kpi-btn {
          display: block;
          width: 100%;
          text-align: left;
          cursor: pointer;
          background: #fff;
          border: 1px solid var(--woah-line);
          border-radius: 10px;
          padding: 0.55rem 0.75rem 0.6rem;
          transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        button.ahr-kpi-btn:hover,
        button.ahr-kpi-btn:focus {
          border-color: var(--woah-coral);
          box-shadow: 0 0 0 2px rgba(228, 87, 46, 0.18);
          outline: none;
        }
        button.ahr-kpi-btn .ahr-kpi-hint {
          color: var(--woah-blue);
          font-weight: 600;
        }
        .ahr-attention-detail {
          background: #fff;
          border: 1px solid var(--woah-line);
          border-left: 3px solid var(--woah-coral);
          border-radius: 10px;
          padding: 0.65rem 0.9rem;
          margin: 0 0 0.85rem;
        }
        .ahr-attention-detail h6 {
          margin: 0 0 0.4rem;
          color: var(--woah-blue-deep);
          font-weight: 700;
          font-size: 0.85rem;
        }
        .ahr-attention-detail ul {
          margin: 0;
          padding-left: 1.1rem;
        }
        .ahr-attention-detail li {
          margin-bottom: 0.25rem;
          font-size: 0.88rem;
        }

        .ahr-story { margin-bottom: 0.75rem; }
        .ahr-story-step {
          border: 1px solid var(--woah-line);
          border-radius: 10px;
          padding: 0.65rem 0.85rem;
          margin-bottom: 0.45rem;
          background: #fff;
          border-left: 4px solid var(--woah-blue);
        }
        .ahr-story-step-title {
          font-size: 0.78rem;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: var(--woah-blue-deep);
          margin-bottom: 0.2rem;
        }
        .ahr-story-step p { font-size: 0.9rem; color: var(--woah-ink); }
        .ahr-story-info { border-left-color: var(--woah-blue-mid); background: #f3f8fc; }
        .ahr-story-warn { border-left-color: var(--woah-coral); background: var(--woah-coral-soft); }
        .ahr-story-ok { border-left-color: var(--woah-sage); background: #eef7f4; }
        .ahr-story-neutral { border-left-color: #94a3b8; }

        .ahr-eq {
          background: #0f2740;
          color: #e8f2fa;
          border: 1px solid #1a4a6e;
          border-radius: 8px;
          padding: 0.75rem 1rem;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.82rem;
          line-height: 1.45;
          white-space: pre-wrap;
          overflow-x: auto;
          margin: 0.5rem 0 0.85rem;
        }
        """
    )


def app_ui(data: AppData):
    disease_all = {"ALL": "All diseases (Radar overview)", **{k: v.name for k, v in data.diseases.items()}}
    disease_case = {k: v.name for k, v in data.diseases.items()}
    # Latest first so the select defaults visibly to the most recent cut-off.
    as_of_dates_desc = list(reversed(data.as_of_dates)) if data.as_of_dates else []
    as_of_choices = {d: d for d in as_of_dates_desc}
    default_as_of = as_of_dates_desc[0] if as_of_dates_desc else None
    country_choices = {iso: spec.name for iso, spec in data.countries.items()}
    # UKR|ASF has the richest scored panel for demos (alerts + INFUR + intel + SMR).
    default_country = (
        "UKR" if "UKR" in country_choices
        else ("ROU" if "ROU" in country_choices else next(iter(country_choices), None))
    )
    default_disease = "ASF" if "ASF" in disease_case else next(iter(disease_case), None)

    return ui.page_fluid(
        _ahr_css(),
        ui.div(
            {"class": "ahr-shell"},
            ui.div(
                {"class": "ahr-header"},
                ui.div(
                    {"class": "ahr-header-inner"},
                    ui.div(
                        ui.p({"class": "ahr-brand"}, "WOAH Datathon · Challenge 1"),
                        ui.h1({"class": "ahr-title"}, "Animal Health Radar"),
                        ui.p(
                            {"class": "ahr-subtitle"},
                            "Early detection · nowcasting · short-term forecasting under delayed reporting",
                        ),
                    ),
                    ui.div(
                        {"class": "ahr-header-meta"},
                        ui.div({"class": "ahr-pill"}, "Model estimates — not confirmed outbreaks"),
                        ui.div(f"data_mode = {data.data_mode}"),
                    ),
                ),
            ),
            ui.div({"class": "ahr-accent-bar"}),
            ui.div(
                {"class": "ahr-main"},
                ui.navset_tab(
                    ui.nav_panel("Intro", intro_panel(data)),
                    ui.nav_panel(
                        "Global Radar",
                        ui.div(
                            {"class": "ahr-tab-body"},
                            tab_explainer(
                                question="Where should an epidemiologist look first this week?",
                                what="A triage map and ranked country table built from MODEL ESTIMATES "
                                "(investigation priority, early-warning probability, latent activity, reporting gap).",
                                how="1) Set as-of and disease in the left panel. "
                                "2) Keep Investigation priority as the default map layer. "
                                "3) Note a top country in the priority queue, then open Investigate and select it there.",
                                remember="Colours are not confirmed outbreak counts. Darker = higher estimated need to look — not proof of infection.",
                            ),
                            ui.layout_sidebar(
                                ui.sidebar(
                                    ui.div(
                                        {"class": "ahr-sidebar-block"},
                                        ui.p({"class": "ahr-sidebar-label"}, "Scope"),
                                        ui.input_select(
                                            "as_of_radar",
                                            "As-of date (knowledge cut-off)",
                                            as_of_choices,
                                            selected=default_as_of,
                                        ),
                                        ui.input_select(
                                            "disease_radar",
                                            "Disease",
                                            disease_all,
                                            selected=default_disease,
                                        ),
                                    ),
                                    ui.hr(),
                                    ui.div(
                                        {"class": "ahr-sidebar-block"},
                                        ui.p({"class": "ahr-sidebar-label"}, "Map"),
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
                                    ),
                                    ui.p("Layer guide", class_="fw-semibold small mb-1 mt-2"),
                                    LAYER_HELP,
                                    ui.hr(),
                                    ui.p(
                                        "Country is chosen on Investigate / Forecast. "
                                        "After you spot a priority country here, switch tabs and select it there.",
                                        class_="text-muted small mb-0",
                                    ),
                                    width=320,
                                ),
                                ui.div(ui.output_text("banner"), class_="alert alert-warning py-2"),
                                section_note(
                                    "Summary strip",
                                    "How many places look elevated right now under the current as-of and disease filter. "
                                    "Click “Need analyst attention” to list the countries.",
                                ),
                                ui.output_ui("radar_kpis"),
                                ui.output_ui("radar_attention_detail"),
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
                            {"class": "ahr-tab-body"},
                            tab_explainer(
                                question="For this country × disease, what is officially visible versus what we estimate is happening — and why?",
                                what="A case file: KPIs, latent-vs-observed time series, evidence timeline, “why this alert”, "
                                "counterfactual ablations, feature contributions, and provenance.",
                                how="1) Set Country, Disease, and As-of in This case. "
                                "2) Compare Observed vs Estimated latent and the Reporting gap. "
                                "3) Read Why this alert + Counterfactuals before acting on a score.",
                                remember="This is epidemic intelligence support, not a confirmation of outbreak. Official verification still decides response.",
                            ),
                            ui.layout_sidebar(
                                ui.sidebar(
                                    ui.p({"class": "ahr-sidebar-label"}, "This case"),
                                    ui.input_select(
                                        "country_inv",
                                        "Country",
                                        country_choices,
                                        selected=default_country,
                                    ),
                                    ui.input_select(
                                        "disease_inv",
                                        "Disease",
                                        disease_case,
                                        selected=default_disease,
                                    ),
                                    ui.input_select(
                                        "as_of_inv",
                                        "As-of date (knowledge cut-off)",
                                        as_of_choices,
                                        selected=default_as_of,
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
                                    width=300,
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
                                    section_note(
                                        "Media headlines",
                                        "Article / report titles knowable at this as-of (PADI-web, BEACON, EIOS when available). "
                                        "Full article bodies are not stored — open the URL for the original text.",
                                    ),
                                    ui.output_ui("inv_media_headlines"),
                                    section_note(
                                        "Provenance ledger",
                                        "Source metadata linked to this country × disease under the as-of cut-off.",
                                    ),
                                    ui.output_data_frame("inv_provenance"),
                                ),
                            ),
                        ),
                    ),
                    ui.nav_panel(
                        "Forecast & Replay",
                        ui.div(
                            {"class": "ahr-tab-body"},
                            tab_explainer(
                                question="What is likely next — and how early would we have seen concern if we froze knowledge on a past date?",
                                what="Two tools in one tab: (A) short-term probabilistic forecast fans (7/14/28 days), "
                                "and (B) historical replay of what the model knew at the selected as-of, with lead-time against later official outcomes.",
                                how="1) Set Country / Disease / As-of in the left panel. "
                                "2) Choose the forecast horizon. "
                                "3) Read the forecast summary + fan chart, then Replay for lead time.",
                                remember="Forecasts are distributions with uncertainty, not single certainties. Replay outcomes after as-of are labels for evaluation.",
                            ),
                            ui.layout_sidebar(
                                ui.sidebar(
                                    ui.div(
                                        {"class": "ahr-sidebar-block"},
                                        ui.p({"class": "ahr-sidebar-label"}, "Case"),
                                        ui.input_select(
                                            "country_fc",
                                            "Country",
                                            country_choices,
                                            selected=default_country,
                                        ),
                                        ui.input_select(
                                            "disease_fc",
                                            "Disease",
                                            disease_case,
                                            selected=default_disease,
                                        ),
                                        ui.input_select(
                                            "as_of_fc",
                                            "As-of date (knowledge cut-off)",
                                            as_of_choices,
                                            selected=default_as_of,
                                        ),
                                    ),
                                    ui.hr(),
                                    ui.div(
                                        {"class": "ahr-sidebar-block"},
                                        ui.p({"class": "ahr-sidebar-label"}, "Horizon"),
                                        ui.input_radio_buttons(
                                            "fc_horizon",
                                            "Primary horizon for the summary cards",
                                            {"7": "7 days", "14": "14 days", "28": "28 days"},
                                            selected="14",
                                        ),
                                    ),
                                    ui.p(
                                        "Replay uses the as-of above as Day 0; later rows are evaluation outcomes only.",
                                        class_="small text-muted mb-0",
                                    ),
                                    width=300,
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
                                    ui.card_header("B · Historical replay — early-warning storyline"),
                                    section_note(
                                        "Purpose",
                                        "Follow the story: intelligence → model WATCH/ALERT → last/next INFUR report → "
                                        "INFUR lead time → SMR semester check when INFUR is silent (endemic/stable or "
                                        "SMR-only reporting paths).",
                                    ),
                                    ui.output_ui("fc_replay_summary"),
                                    section_note(
                                        "Week-by-week table",
                                        "Rows ≤ as-of were knowable then; rows after as-of are evaluation outcomes only.",
                                    ),
                                    ui.output_data_frame("fc_replay_table"),
                                ),
                            ),
                        ),
                    ),
                    ui.nav_panel("Data sources", data_sources_panel(data)),
                    ui.nav_panel("Methodology", methodology_panel(data)),
                    id="main_nav",
                ),
            ),
        ),
    )
