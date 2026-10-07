"""Static narrative panels: Intro, Data sources, Methodology + shared explainers."""

from __future__ import annotations

from shiny import ui

from dashboard.data_loader import AppData


def tab_explainer(
    question: str,
    what: str,
    how: str,
    remember: str,
) -> ui.Tag:
    """Friendly one-screen briefing for an analysis tab."""
    return ui.div(
        {"class": "ahr-explain mb-3"},
        ui.div(
            {"class": "ahr-explain-q"},
            ui.tags.strong("Question this tab answers: "),
            question,
        ),
        ui.layout_columns(
            ui.div(
                ui.tags.strong("What you see"),
                ui.p(what, class_="mb-0 small"),
            ),
            ui.div(
                ui.tags.strong("How to use it"),
                ui.p(how, class_="mb-0 small"),
            ),
            ui.div(
                ui.tags.strong("Remember"),
                ui.p(remember, class_="mb-0 small"),
            ),
            col_widths=(4, 4, 4),
        ),
    )


def section_note(title: str, body: str) -> ui.Tag:
    return ui.div(
        {"class": "ahr-section-note mb-2"},
        ui.tags.strong(title + " — "),
        ui.tags.span(body, class_="small"),
    )


def intro_panel(data: AppData) -> ui.Tag:
    mode = data.data_mode.upper()
    n_pred = len(data.predictions)
    n_asof = len(data.as_of_dates)
    n_countries = len(data.countries)
    diseases = ", ".join(data.diseases.keys())

    return ui.div(
        {"class": "ahr-prose px-4 py-3"},
        ui.div(
            {"class": "ahr-hero mb-4 p-4 rounded"},
            ui.h2("Animal Health Radar", class_="mb-1"),
            ui.h4(
                "See what official surveillance has not fully observed yet — and how much earlier we could have known.",
                class_="fw-normal",
            ),
            ui.p(
                "WOAH International Datathon 2026 · Challenge 1: Early detection, nowcasting and forecasting "
                "of animal-health events under incomplete and delayed reporting.",
                class_="mb-0 small",
            ),
        ),
        ui.div(
            {"class": "alert alert-info"},
            ui.tags.strong("How to use this demo (2 minutes): "),
            "① Read this Intro → ② open ",
            ui.tags.em("Global Radar"),
            " to triage where to look → ③ open ",
            ui.tags.em("Investigate"),
            " and pick a country → ④ use ",
            ui.tags.em("Forecast & Replay"),
            " for “what next?” and “what would we have known then?”",
        ),
        ui.layout_columns(
            ui.card(
                ui.card_header("The problem"),
                ui.p(
                    "Animal disease events exist in the world before they appear in official systems "
                    "such as WOAH WAHIS. Reporting takes days to weeks. Media and intelligence often "
                    "arrive earlier — but they are noisy and duplicated. Looking only at the latest "
                    "official map systematically understates risk at the leading edge of an epidemic."
                ),
            ),
            ui.card(
                ui.card_header("Our answer"),
                ui.p(
                    "Animal Health Radar is a ",
                    ui.tags.strong("probabilistic evidence-fusion system"),
                    ". It separates the ",
                    ui.tags.strong("disease process"),
                    " (what is probably happening) from the ",
                    ui.tags.strong("observation process"),
                    " (what has been officially reported so far), then projects 7 / 14 / 28-day trajectories "
                    "with explicit uncertainty."
                ),
            ),
            ui.card(
                ui.card_header("Why it matters"),
                ui.p(
                    "Earlier, honest situational awareness gives veterinary services time to verify, "
                    "target surveillance, and pre-position response — without mistaking a model score "
                    "for a confirmed outbreak. That distinction is the scientific heart of Challenge 1."
                ),
            ),
            col_widths=(4, 4, 4),
        ),
        ui.h4("The core idea", class_="mt-4"),
        ui.div(
            {"class": "ahr-flow p-3 mb-3 rounded text-center"},
            ui.tags.div("TRUE / LATENT DISEASE STATE", class_="fw-semibold"),
            ui.tags.div("↓", class_="my-1"),
            ui.tags.div("DETECTION · REPORTING DELAY · PUBLICATION", class_="text-muted"),
            ui.tags.div("↓", class_="my-1"),
            ui.tags.div("OFFICIAL OBSERVATION (e.g. WAHIS)", class_="fw-semibold"),
        ),
        ui.div(
            {"class": "ahr-callout"},
            ui.p(
                "Every number in this app is a ",
                ui.tags.strong("MODEL ESTIMATE"),
                " computed under a chosen ",
                ui.tags.strong("as-of date"),
                " — the knowledge cut-off. Nothing published after that date is allowed into the prediction. "
                "That is how we prevent “cheating with the future” and how Historical Replay can demonstrate lead time.",
                class_="mb-3",
            ),
            ui.h4("What each analysis tab answers"),
            ui.tags.ul(
                ui.tags.li(
                    ui.tags.strong("Global Radar — "),
                    "Where should an epidemiologist look first this week? "
                    "Triage map + ranked table of investigation priority (not outbreak counts).",
                ),
                ui.tags.li(
                    ui.tags.strong("Investigate — "),
                    "For one country × disease: what is reported vs what we estimate is happening, "
                    "why the alert fired, and which evidence families drove it.",
                ),
                ui.tags.li(
                    ui.tags.strong("Forecast & Replay — "),
                    "What is likely in the next 7/14/28 days, and if we freeze knowledge on a past date, "
                    "how early would the model have raised concern before official counts rose?",
                ),
                class_="mb-0",
            ),
        ),
        ui.h4("Key terms (used everywhere)"),
        ui.layout_columns(
            ui.card(
                ui.card_header("As-of date"),
                ui.p(
                    "The knowledge cut-off shared by all analysis tabs. "
                    "Only information that was already available on that day may enter the model."
                ),
            ),
            ui.card(
                ui.card_header("Latent vs observed"),
                ui.p(
                    "Observed = official burden visible so far. "
                    "Latent = model estimate of underlying activity after accounting for delay and incomplete reporting."
                ),
            ),
            ui.card(
                ui.card_header("Reporting gap"),
                ui.p(
                    "Difference between estimated latent activity and what has been officially observed — "
                    "a quantitative “how much might still be unseen?” signal."
                ),
            ),
            col_widths=(4, 4, 4),
        ),
        ui.h4("This build at a glance", class_="mt-3"),
        ui.layout_columns(
            ui.value_box("Diseases", diseases or "—"),
            ui.value_box("Countries in panel", str(n_countries)),
            ui.value_box("As-of weeks scored", str(n_asof)),
            ui.value_box("Prediction rows", str(n_pred)),
            col_widths=(3, 3, 3, 3),
        ),
        ui.p(
            "Geography is ",
            ui.tags.strong("global"),
            " (WOAH membership panel). Official WAHIS INFUR is worldwide; "
            "epidemic-intelligence caches (PADI / BEACON / EIOS) may still be denser in some regions until re-fetched. "
            "Countries without recent notifications can still appear with low / baseline scores.",
            class_="small text-muted",
        ),
        ui.div(
            {"class": "alert alert-warning mt-3"},
            ui.tags.strong(f"Data mode: {mode}. "),
            (
                "Official observation is real WAHIS INFUR (offline extract; no API). "
                "SMR semester status is kept separate from outbreak counts. "
                "Media/environment enrichment may still use labelled sample files — "
                "see Data sources. Never treat map colours as confirmed outbreaks."
                if data.data_mode in {"pilot", "offline"}
                else "The demo runs on a clearly labelled synthetic corpus so the full "
                "pipeline is reproducible offline. Drop real INFUR/SMR under data/raw/ "
                "and set data_mode=pilot. Never treat map colours as confirmed outbreaks."
            ),
        ),
        ui.p(
            ui.tags.em(
                "Positioning: not “an AI outbreak detector” — a transparent system for early warning, "
                "latent-state nowcasting, reporting-gap estimation, and short-term probabilistic forecasting."
            ),
            class_="text-muted small",
        ),
    )


def data_sources_panel(data: AppData) -> ui.Tag:
    return ui.div(
        {"class": "ahr-prose px-4 py-3"},
        ui.h2("Data sources"),
        tab_explainer(
            question="Which evidence streams feed the Radar, and how do we avoid double-counting?",
            what="A layered catalogue: official WAHIS observation, epidemic intelligence, environment, and livestock context.",
            how="Treat this as the evidence dictionary. When Investigate shows a contribution, map it back to a family here.",
            remember="Twenty articles about one outbreak are not twenty independent events — independence clusters protect the signal.",
        ),
        ui.p(
            "Sources are not added naïvely. Each record carries provenance (who, when knowable, lineage) "
            "and an independence cluster so duplicated media does not inflate risk."
        ),
        ui.h4("Primary official observation"),
        ui.tags.ul(
            ui.tags.li(
                ui.tags.strong("WAHIS (WOAH) — "),
                "Reference official notifications. Used as the observation process and for retrospective "
                "evaluation — ",
                ui.tags.em("not"),
                " as absolute truth about latent disease. Real extracts: INFUR (event-driven) and optional SMR "
                "(semester status). INFUR and SMR use different ID spaces and must not be double-counted."
            ),
            ui.tags.li(
                ui.tags.strong("EMPRES-i — "),
                "Often republishes WAHIS. Skipped in pilot mode to avoid double-counting INFUR; "
                "when used, marked downstream-of-official in the same independence cluster."
            ),
        ),
        ui.h4("Epidemic intelligence (non-official)"),
        ui.tags.ul(
            ui.tags.li(ui.tags.strong("GDELT / ProMED / HealthMap — "), "Media signals → volume anomalies, diversity, acceleration — never raw article count as outbreak probability."),
            ui.tags.li(
                ui.tags.strong("PADI-web — "),
                "Real public JSON API (padi-web.cirad.fr/en/articles/api/) for CIRAD event extractions; cached under data/raw/padiweb/."
            ),
            ui.tags.li(
                ui.tags.strong("BEACON — "),
                "Real public API (api.beaconbio.org) for curated reports; cached offline under data/raw/beacon/."
            ),
            ui.tags.li(
                ui.tags.strong("EIOS — "),
                "Real recent feed from the public WHO Pandemic Hub newsmap (EIOS-tagged open news); "
                "optional full community-portal Excel/CSV under data/raw/eios/."
            ),
        ),
        ui.h4("Environment & exposure"),
        ui.tags.ul(
            ui.tags.li(ui.tags.strong("ERA5 / ERA5-Land — "), "Temperature, precipitation and suitability proxies with realistic availability lag."),
            ui.tags.li(ui.tags.strong("WorldClim — "), "Climatological baseline / seasonality — not real-time weather."),
            ui.tags.li(ui.tags.strong("GLW4 / FAOSTAT — "), "Livestock exposure context (static / lagged), labelled as contextual — not current census truth."),
        ),
        ui.h4("Extension architecture (stubs)"),
        ui.p(
            "UN Comtrade, Global Forest Watch, WTO SPS and Simulation Exercises are adapter-ready. "
            "They must not block the MVP pipeline."
        ),
        ui.h4("Evidence hierarchy (conceptual)"),
        ui.tags.ol(
            ui.tags.li("Official confirmed event"),
            ui.tags.li("Independent veterinary / government intelligence"),
            ui.tags.li("Curated epidemic intelligence"),
            ui.tags.li("Independent media"),
            ui.tags.li("Repeated / duplicated media"),
            ui.tags.li("Weak contextual signal"),
        ),
        ui.p(
            "Weights are learned/calibrated in the model — not hand-authored probabilities from an LLM.",
            class_="text-muted",
        ),
        ui.div(
            {"class": "alert alert-secondary"},
            f"Current app data_mode = {data.data_mode}. Offline INFUR/SMR live under ",
            ui.tags.code("data/raw/"),
            "; enrichment samples under ",
            ui.tags.code("data/sample/"),
            " are flagged synthetic/mock in provenance.",
        ),
    )


def methodology_panel(data: AppData) -> ui.Tag:
    return ui.div(
        {"class": "ahr-prose px-4 py-3"},
        ui.h2("Methodology"),
        tab_explainer(
            question="How do we estimate what is happening now, what is under-observed, and what is next?",
            what="Four model families: reporting delay, latent nowcast, early warning, and short-term forecast — kept separate on purpose.",
            how="Use this tab when you need the scientific defence. Use Investigate for the case-level “why”.",
            remember="As-of discipline is non-negotiable: no future publications may leak into historical scores.",
        ),
        ui.p(
            "Four questions → four model families, deliberately separate. Prefer transparent statistical "
            "models over black-box sequence learners for a datathon defence."
        ),
        ui.layout_columns(
            ui.card(
                ui.card_header("1. Reporting delay"),
                ui.p(
                    "Estimate how long events take to become officially visible (onset → publication), "
                    "with ",
                    ui.tags.strong("right-truncated likelihood"),
                    " so recent incomplete weeks do not pretend delays are short. Partial pooling by disease × surveillance capacity."
                ),
            ),
            ui.card(
                ui.card_header("2. Latent nowcast"),
                ui.p(
                    "Given what is visible today, estimate current latent burden and the ",
                    ui.tags.strong("reporting gap"),
                    ". Ascertainment (ever detected?) is an ",
                    ui.tags.strong("explicit prior"),
                    " — never silently claimed as estimated from WAHIS alone."
                ),
            ),
            ui.card(
                ui.card_header("3. Early warning"),
                ui.p(
                    "Calibrated probability that ",
                    ui.tags.strong("official visibility"),
                    " appears or escalates within ~28 days given information at as-of T. "
                    "Baselines (seasonal, EWMA, CUSUM, official-only) must be beaten before we claim value."
                ),
            ),
            ui.card(
                ui.card_header("4. Short-term forecast"),
                ui.p(
                    "7 / 14 / 28-day predictive distributions via a CRPS-weighted ensemble "
                    "(NegBin GLM + damped trend + seasonal climatology). Intervals and exceedance probabilities — not single points."
                ),
            ),
            col_widths=(6, 6, 6, 6),
        ),
        ui.h4("As-of discipline (no leakage)", class_="mt-3"),
        ui.p(
            "For any prediction stamped with date T, only records with ",
            ui.tags.code("available_from ≤ T"),
            " may enter features or parameters. Automated tests under ",
            ui.tags.code("tests/leakage/"),
            " fail loudly if future publications contaminate historical scores."
        ),
        ui.h4("Explainability & counterfactuals"),
        ui.p(
            "Investigate shows feature contributions (SHAP or occlusion) and ",
            ui.tags.strong("family ablations"),
            ": re-score the fitted model after removing intelligence, environment, livestock, etc. "
            "Those deltas are computed — not invented for the slide deck."
        ),
        ui.h4("Historical replay"),
        ui.p(
            "Pick a past as-of date. The system reconstructs what was knowable then, shows the alert path, "
            "and compares to official outcomes that arrived later — the flagship demonstration of lead time."
        ),
        ui.h4("Language we use carefully"),
        ui.tags.ul(
            ui.tags.li(ui.tags.em("estimated latent activity"), " / ", ui.tags.em("estimated reporting gap")),
            ui.tags.li(ui.tags.em("probability of elevated / officially visible activity")),
            ui.tags.li(ui.tags.em("early-warning signal"), " / ", ui.tags.em("MODEL ESTIMATE")),
        ),
        ui.p(
            "We avoid “hidden outbreak confirmed”, “country is hiding outbreaks”, or “AI detected an outbreak” "
            "unless an official confirmation exists.",
            class_="text-muted",
        ),
        ui.p(
            ui.tags.small(
                "See also docs/METHODOLOGY.md, docs/TARGET_DEFINITION.md, docs/DECISIONS.md, docs/MODEL_CARD.md"
            )
        ),
    )
