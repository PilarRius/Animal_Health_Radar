"""Static narrative panels: Intro, Data sources, Methodology + shared explainers."""

from __future__ import annotations

from shiny import ui

from dashboard.data_loader import AppData
from dashboard.licensing import data_licensing_section, methodology_citations_section


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
        ui.tags.strong(f"{title} — "),
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
                    "official map systematically understates risk at the leading edge of an outbreak."
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
            "The country list is ",
            ui.tags.strong("global"),
            " (WOAH Members). Official WAHIS notifications cover the world, so any Member "
            "can appear on the map. Extra media/intelligence feeds (PADI-web, BEACON, EIOS) "
            "are stronger in some regions than others in this build — a quiet country often "
            "means little recent evidence, not that disease risk is zero. Low or baseline "
            "scores are normal where there are few recent official reports.",
            class_="small text-muted",
        ),
        ui.div(
            {"class": "alert alert-warning mt-3"},
            ui.tags.strong(f"Data mode: {mode}. "),
            (
                ui.tags.span(
                    "What is real in this demo: official WAHIS ",
                    ui.tags.strong("INFUR"),
                    " outbreak notifications from an offline file extract (no live API). "
                    "WAHIS ",
                    ui.tags.strong("SMR"),
                    " (six-monthly reports) are ",
                    ui.tags.em("not"),
                    " counted as outbreaks; Forecast & Replay may only use a later SMR "
                    "as a coarse check when INFUR goes quiet (e.g. endemic / stable situations). "
                    "Some media and climate layers may still be labelled sample data — "
                    "see Data sources. Map colours and ranks are ",
                    ui.tags.strong("model estimates"),
                    ", never confirmed outbreaks."
                )
                if data.data_mode in {"pilot", "offline"}
                else ui.tags.span(
                    "This build uses a clearly labelled synthetic corpus so the pipeline "
                    "runs offline. For real INFUR/SMR, place extracts under ",
                    ui.tags.code("data/raw/"),
                    " and set data_mode=pilot. Map colours are model estimates, never confirmed outbreaks."
                )
            ),
        ),
        ui.p(
            ui.tags.small(
                "Not an official WOAH/FAO/WHO product. Data licences and suggested citations: "
                "Data sources tab · methodology literature: Methodology tab."
            ),
            class_="text-muted",
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
                " as absolute truth about latent disease. Real extracts: INFUR (event-driven) and SMR "
                "(semester status). INFUR and SMR use different ID spaces and must not be double-counted. "
                "Stable/endemic framing often means Members leave INFUR and report only on SMR; "
                "non-notifiable diseases may never appear on INFUR."
            ),
            ui.tags.li(
                ui.tags.strong("EMPRES-i — "),
                "Often republishes WAHIS. Skipped in pilot mode to avoid double-counting INFUR; "
                "when used, marked downstream-of-official in the same independence cluster."
            ),
        ),
        ui.h4("Epidemic intelligence (non-official)"),
        ui.p(
            "These feeds are ",
            ui.tags.em("not"),
            " official outbreak confirmations. They supply early, noisy context that the model "
            "turns into features (volume anomalies, curation intensity, etc.). All three sit in "
            "the same media independence cluster so overlapping stories do not triple-count.",
            class_="small text-muted",
        ),
        ui.tags.ul(
            ui.tags.li(
                ui.tags.strong("GDELT — "),
                "Global news machine: counts of online articles mentioning animal-disease themes "
                "by country (and related tone / language / outlet metadata). ",
                ui.tags.em("What we use: "),
                "weekly ",
                ui.tags.strong("abnormal volume"),
                " (vs a country’s own recent baseline), ",
                ui.tags.strong("acceleration"),
                " (is coverage speeding up?), ",
                ui.tags.strong("source diversity"),
                ", and a simple ",
                ui.tags.strong("tone negativity"),
                " index. ",
                ui.tags.em("What we do not use: "),
                "raw article counts as “outbreak probability” — many articles can be one story."
            ),
            ui.tags.li(
                ui.tags.strong("ProMED (ISID) — "),
                "Human-curated mailing-list posts on emerging infectious diseases (often with "
                "moderator commentary). Sparse but higher signal-to-noise than bulk news. ",
                ui.tags.em("What we use: "),
                "weekly ",
                ui.tags.strong("post counts"),
                ", a ",
                ui.tags.strong("confidence-weighted"),
                " intensity (confirmed / suspected / unverified), and the share of posts with "
                "curator comments. ",
                ui.tags.em("What we do not use: "),
                "anomaly z-scores — the series is too sparse for a control chart to be meaningful."
            ),
            ui.tags.li(
                ui.tags.strong("HealthMap — "),
                "Boston Children’s Hospital aggregator of geo-coded disease alerts drawn from "
                "open web / news / official-style feeds (often overlapping GDELT and ProMED). ",
                ui.tags.em("What we use: "),
                "weekly ",
                ui.tags.strong("unique alert"),
                " volume and its anomaly, plus ",
                ui.tags.strong("duplicate share"),
                " and ",
                ui.tags.strong("official-feed share"),
                " so we can see how much is new vs echoed. ",
                ui.tags.em("Main role here: "),
                "geolocation / aggregation context — not treated as fully independent evidence."
            ),
            ui.tags.li(
                ui.tags.strong("PADI-web — "),
                "CIRAD automated extraction of animal-disease events from multilingual news "
                "(structured fields such as disease, place, date). Real public JSON API; "
                "cached under ",
                ui.tags.code("data/raw/padiweb/"),
                "."
            ),
            ui.tags.li(
                ui.tags.strong("BEACON — "),
                "Curated biosurveillance reports (title, location, disease tags) from a public API. "
                "Cached under ",
                ui.tags.code("data/raw/beacon/"),
                "."
            ),
            ui.tags.li(
                ui.tags.strong("EIOS — "),
                "EIOS-tagged open news via the public WHO Pandemic Hub newsmap (recent items); "
                "optional full community-portal Excel/CSV under ",
                ui.tags.code("data/raw/eios/"),
                " for authorised users only."
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
        data_licensing_section(),
    )


def _eq(*parts: str) -> ui.Tag:
    """Monospace equation block for the Methodology tab."""
    return ui.pre({"class": "ahr-eq"}, "\n".join(parts))


def methodology_panel(data: AppData) -> ui.Tag:
    return ui.div(
        {"class": "ahr-prose px-4 py-3"},
        ui.h2("Methodology"),
        tab_explainer(
            question="How do we estimate what is happening now, what is under-observed, and what is next?",
            what="Four model families with explicit likelihoods / targets / parameters: reporting delay, "
            "latent nowcast, early warning, and short-term forecast — kept separate on purpose.",
            how="Read each section below for the maths and pilot config. Use Investigate for case-level “why”.",
            remember="As-of discipline is non-negotiable: available_from ≤ T. Full write-up: docs/METHODOLOGY.md.",
        ),
        ui.p(
            "Generative story (disease → detection → delay → official visibility):"
        ),
        _eq(
            "N_true  --(ascertainment a)-->  N_eventually_reportable",
            "       --(delay D)---------->  O_visible_at_T",
        ),
        ui.p(
            "Pilot panel frequency W-MON; data cut-off 2026-06-29; MC draws = 800. "
            f"Current app data_mode = {data.data_mode}."
        ),
        # ----- 1 delay -----
        ui.h4("1 · Reporting delay", class_="mt-4"),
        ui.p(
            "Object: delay D (days) from reference/onset date t to official knowability. "
            "At analysis date T an event is observed only if D ≤ T − t (right truncation). "
            "Naive fits without truncation make delays look too short."
        ),
        ui.p(ui.tags.strong("Truncated likelihood:")),
        _eq("L(θ) = ∏_i  f(d_i | θ) / F(T − t_i | θ)"),
        ui.p(
            "Families per group (disease × surveillance tier): discretised log-normal (μ, σ) "
            "or NegBin (mean μ, dispersion α); AIC selects. Partial pooling shrinks thin strata "
            "toward disease then global fits with weight n/(n+κ), κ = 40."
        ),
        ui.p(
            "Operational: max_delay_days = 90; delay_refit_interval_weeks = 8; "
            "reporting probability p_w(T) = F(T − t_w | θ̂), floored at min_reporting_probability = 0.25."
        ),
        # ----- 2 nowcast -----
        ui.h4("2 · Latent nowcast", class_="mt-4"),
        ui.p(
            "Given visible count O_w for reference week w and delay-implied p_w, estimate the "
            "not-yet-reported remainder U_w (NegBin posterior predictive) then inflate by "
            "an ",
            ui.tags.strong("explicit ascertainment prior"),
            " a (never claimed as estimated from WAHIS alone)."
        ),
        _eq(
            "E[U_w] = (a0 + O_w) · (1 − p_w) / (b0 + p_w)",
            "N̂_w = O_w + U_w",
            "latent_w = N̂_w / a ,   a ~ Beta(α_tier, β_tier) · m_disease",
            "gap_w = hidden_w / latent_w",
        ),
        ui.p(
            "Ascertainment Beta means (pilot): high ≈ 0.88 (α=22, β=3); medium ≈ 0.76 (16, 5); "
            "low ≈ 0.56 (10, 8). Disease multipliers: HPAI m=1.00, ASF m=0.92. "
            "Gap bands: minor ≥ 0.25, moderate ≥ 0.50, severe ≥ 0.72."
        ),
        ui.p(
            "Week-wise estimates are smoothed with a local-level (random-walk) state-space model "
            "on the log scale over nowcast_window_weeks = 12 (Rauch–Tung–Striebel). "
            "Uncertainty still comes from Monte-Carlo draws of U_w, p_w, and a."
        ),
        # ----- 3 EW -----
        ui.h4("3 · Early warning", class_="mt-4"),
        ui.p(
            "Target is ",
            ui.tags.strong("official visibility / escalation"),
            ", not “latent outbreak confirmed”. Horizon H = 28 days; run-rate window = 8 weeks; "
            "escalation factor φ = 1.5:"
        ),
        _eq(
            "Y_T = 1{  publications in (T, T+H]",
            "        ≥ max( 1 ,  φ · r̂_T · H/7 )  }",
        ),
        ui.p(
            "Quiet entities → emergence (threshold 1). Already reporting → escalation beyond run-rate. "
            "Primary model: gradient boosting on the point-in-time design matrix; "
            "calibration = isotonic on a later window."
        ),
        ui.p(
            ui.tags.strong("Temporal splits (pilot): "),
            "train as_of ≤ 2025-06-30; calibration ≤ 2025-12-29; test after. No shuffling."
        ),
        ui.p(
            ui.tags.strong("Alert bands on calibrated π̂: "),
            "NONE 0.00 · INFO 0.08 · WATCH 0.20 · ALERT 0.40 · CRITICAL 0.65. "
            "Hysteresis de-escalate margin 0.05. Explanations: SHAP or occlusion "
            "Δ_j = f(x) − f(x with feature j → training median); family counterfactuals likewise."
        ),
        # ----- 4 forecast -----
        ui.h4("4 · Short-term forecast (7 / 14 / 28 days)", class_="mt-4"),
        ui.p(
            "Target = reported_final: outbreaks with reference week in the horizon that are ",
            ui.tags.strong("eventually"),
            " reported (scorable). Latent scale = reported_final / ascertainment mean, labelled separately."
        ),
        ui.p("CRPS-weighted mixture of three members:"),
        ui.tags.ul(
            ui.tags.li(ui.tags.strong("NegBin GLM — "), "covariates + Fourier seasonality (reactive to new signals)."),
            ui.tags.li(ui.tags.strong("Damped Holt trend — "), "on log(1+y) of vintage-visible series."),
            ui.tags.li(ui.tags.strong("Seasonal climatology — "), "week-of-year mean from prior years."),
        ),
        _eq(
            "w_m ∝ exp( − CRPS_m / (τ · mean_CRPS) ) ,  τ = 0.5 ,  w_m ≥ 0.05",
            "Predictive law = mixture of MC draws (not averaged quantiles)",
        ),
        ui.p(
            "Quantiles {0.05…0.95}; central interval level 0.90. Exceedance: P(count≥1), "
            "threshold multiples, P(increase) with relative margin 0.10 vs current nowcast."
        ),
        # ----- 5 priority -----
        ui.h4("5 · Investigation priority (Radar)", class_="mt-4"),
        ui.p("Policy weights (sum to 1 — not estimated):"),
        _eq(
            "IP = 0.34·π̂ + 0.22·gap + 0.20·(1 − e^{−latent/5})",
            "   + 0.14·clip(forecast_growth,0,1) + 0.10·σ(intel)",
        ),
        ui.p("Bands: moderate ≥ 0.30, high ≥ 0.52, very high ≥ 0.72."),
        # ----- 6 independence -----
        ui.h4("6 · Evidence independence", class_="mt-4"),
        _eq("n_eff = (Σ w_i)² / (wᵀ R w)"),
        ui.p(
            "R from configured clusters (official / media / aggregator / environmental / exposure). "
            "Gates: min n_eff for ALERT = 1.35; for CRITICAL = 2.10."
        ),
        # ----- 7 replay -----
        ui.h4("7 · Historical replay & SMR check", class_="mt-4"),
        ui.p(
            "At as-of T: rebuild scores with available_from ≤ T; mark first WATCH/ALERT; "
            "compare to INFUR final-vintage weeks before/after T for lead time. "
            "If INFUR is silent after T, check SMR semester covariates "
            "(smr_disease_present / new / total outbreaks) knowable after T — ",
            ui.tags.strong("semester validation only"),
            ", never treated as INFUR outbreak events. Stable/endemic and non-notifiable "
            "paths often leave INFUR (see Data sources / WAHIS_INFUR_SMR_DROP.md)."
        ),
        ui.h4("As-of discipline (no leakage)", class_="mt-4"),
        ui.p(
            "Only ",
            ui.tags.code("available_from ≤ T"),
            " may enter features or parameters. Feature family lags (days): intelligence 1, "
            "environmental 6, contextual/FAOSTAT 365. Tests under ",
            ui.tags.code("tests/leakage/"),
            "."
        ),
        ui.h4("Language we use carefully"),
        ui.tags.ul(
            ui.tags.li(ui.tags.em("estimated latent activity"), " / ", ui.tags.em("estimated reporting gap")),
            ui.tags.li(ui.tags.em("probability of elevated / officially visible activity")),
            ui.tags.li(ui.tags.em("early-warning signal"), " / ", ui.tags.em("MODEL ESTIMATE")),
        ),
        ui.p(
            "We avoid “hidden outbreak confirmed”, “country is hiding outbreaks”, or “AI detected an outbreak” "
            "unless an official confirmation exists. Alert thresholds are operational placeholders, "
            "not claimed epidemiologically optimal.",
            class_="text-muted",
        ),
        methodology_citations_section(),
        ui.p(
            ui.tags.small(
                "Full equations & tables: docs/METHODOLOGY.md · also TARGET_DEFINITION.md, "
                "DECISIONS.md, MODEL_CARD.md, INITIAL_MODEL_DESIGN.md"
            )
        ),
    )
