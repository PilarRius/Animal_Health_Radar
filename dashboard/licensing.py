"""Data-source licences, suggested citations, and methodology literature notes.

Aligned with the sibling TVI app (`Datathons/TVI/src/ui/methodology_licensing.py`)
and checked against provider terms (WOAH WAHIS, FAOSTAT CC BY 4.0, Copernicus/ERA5,
GDELT, WorldClim, GLW4, etc.).
"""

from __future__ import annotations

from shiny import ui


# ---------------------------------------------------------------------------
# Canonical rows — keep adapter `licence` strings in sync when editing these.
# ---------------------------------------------------------------------------

DATA_SOURCE_ROWS: list[dict[str, str]] = [
    {
        "source": "WOAH WAHIS (INFUR)",
        "used_for": "Official immediate / follow-up notifications (observation process)",
        "licence": (
            "WOAH public WAHIS interface: published for analysis and risk-based "
            "decision-making. Attribute WOAH + URL; do not commercially redistribute "
            "WOAH site content without permission; no implied endorsement."
        ),
        "citation": (
            "World Organisation for Animal Health (WOAH). WAHIS — Immediate "
            "notifications / follow-up reports (INFUR extracts used in this build). "
            "https://wahis.woah.org/"
        ),
    },
    {
        "source": "WOAH WAHIS (SMR)",
        "used_for": "Six-monthly reports; semester status / endemic validation (covariates)",
        "licence": "Same WOAH WAHIS terms as INFUR — attribution required; no endorsement.",
        "citation": (
            "World Organisation for Animal Health (WOAH). WAHIS — Six-Monthly Reports "
            "(SMR extracts used in this build). https://wahis.woah.org/"
        ),
    },
    {
        "source": "FAO EMPRES-i",
        "used_for": "Optional official/intel layer (often WAHIS-derived; skipped in pilot)",
        "licence": (
            "FAO EMPRES-i terms of use / FAO statistical database terms where applicable. "
            "Attribute FAO; no endorsement."
        ),
        "citation": (
            "FAO. EMPRES-i — Global Animal Disease Information System. "
            "https://empres-i.apps.fao.org/"
        ),
    },
    {
        "source": "GDELT Project",
        "used_for": "Media volume / diversity / acceleration signals",
        "licence": (
            "Open for academic, commercial, or governmental use without fee. "
            "Any use or redistribution must cite the GDELT Project and link "
            "https://www.gdeltproject.org/."
        ),
        "citation": (
            "Leetaru, K. & Schrodt, P. (2013). GDELT: Global Data on Events, Language, "
            "and Tone, 1979–2012. ISA Annual Convention. "
            "https://www.gdeltproject.org/"
        ),
    },
    {
        "source": "PADI-web (CIRAD)",
        "used_for": "Curated animal-disease news extractions (public API)",
        "licence": (
            "CIRAD PADI-web terms — free limited research / web-monitoring tier for "
            "the public API used here. Attribute PADI-web / CIRAD; respect rate limits."
        ),
        "citation": (
            "Valentin, S., Arsevska, E., Falala, S., de Goër, J., Lancelot, R., "
            "Mercier, A., Rabatel, J. & Roche, M. (2020). PADI-web: A multilingual "
            "event-based surveillance system for monitoring animal infectious diseases. "
            "Computers and Electronics in Agriculture, 169, 105163. "
            "https://doi.org/10.1016/j.compag.2019.105163 — "
            "https://padi-web.cirad.fr/"
        ),
    },
    {
        "source": "BEACON",
        "used_for": "Curated epidemic-intelligence reports (public API)",
        "licence": (
            "Public website / API content — attribute BEACON (beaconbio.org). "
            "Do not imply endorsement; respect provider terms for bulk reuse."
        ),
        "citation": (
            "BEACON. Biosurveillance Ecosystem reports. "
            "https://beaconbio.org/ — https://api.beaconbio.org/"
        ),
    },
    {
        "source": "EIOS / WHO Pandemic Hub newsmap",
        "used_for": "EIOS-tagged open news items (public newsmap)",
        "licence": (
            "Public newsmap content via WHO/JRC EIOS tagging. Full EIOS community "
            "portal exports remain restricted to authorised users — not redistributed "
            "here. Attribute WHO Pandemic Hub / EIOS; no endorsement."
        ),
        "citation": (
            "WHO / European Commission Joint Research Centre. Epidemic Intelligence "
            "from Open Sources (EIOS) — Pandemic Hub newsmap. "
            "https://portal.who.int/pandemichub/newsmap/"
        ),
    },
    {
        "source": "ProMED (ISID)",
        "used_for": "Optional media / curated outbreak posts",
        "licence": "ISID ProMED terms of use — attribute ProMED-mail; no endorsement.",
        "citation": (
            "International Society for Infectious Diseases (ISID). ProMED-mail. "
            "https://promedmail.org/"
        ),
    },
    {
        "source": "HealthMap",
        "used_for": "Optional media / aggregator signals",
        "licence": (
            "HealthMap / Boston Children's Hospital terms of use — attribute HealthMap; "
            "no endorsement."
        ),
        "citation": (
            "HealthMap. Boston Children's Hospital. https://healthmap.org/"
        ),
    },
    {
        "source": "Copernicus ERA5 / ERA5-Land",
        "used_for": "Temperature, precipitation and suitability proxies (lagged)",
        "licence": (
            "Copernicus Climate Change Service products via the CDS — CC BY 4.0 "
            "(from July 2025; previously Licence to use Copernicus Products). "
            "Clear attribution required; state that neither the European Commission "
            "nor ECMWF is responsible for any use made of the information."
        ),
        "citation": (
            "Hersbach, H. et al. (2018/2023). ERA5 hourly data on single levels from "
            "1940 to present. Copernicus Climate Change Service (C3S) Climate Data "
            "Store (CDS). DOI: 10.24381/cds.adbb2d47 (Accessed for this build). "
            "Contains modified Copernicus Climate Change Service information. "
            "Neither the European Commission nor ECMWF is responsible for any use "
            "that may be made of the Copernicus information or data it contains. "
            "https://cds.climate.copernicus.eu/"
        ),
    },
    {
        "source": "WorldClim",
        "used_for": "Climatological baseline / seasonality (not real-time weather)",
        "licence": (
            "Free for academic and other non-commercial use. Redistribution or "
            "commercial use requires prior permission (worldclim.org/about)."
        ),
        "citation": (
            "Fick, S. E. & Hijmans, R. J. (2017). WorldClim 2: new 1-km spatial "
            "resolution climate surfaces for global land areas. International Journal "
            "of Climatology, 37(12), 4302–4315. https://doi.org/10.1002/joc.5086 — "
            "https://www.worldclim.org/"
        ),
    },
    {
        "source": "GLW4 (Gridded Livestock of the World)",
        "used_for": "Livestock exposure context (static / lagged density)",
        "licence": "CC BY 4.0 (FAO catalog / Harvard Dataverse species layers).",
        "citation": (
            "Gilbert, M., Cinardi, G., Da Re, D., Wint, W., Wisser, D. & Robinson, T. P. "
            "(2022). Global livestock distribution in 2015 (GLW4 species layers). "
            "Harvard Dataverse / FAO Gridded Livestock of the World. "
            "https://dataverse.harvard.edu/dataverse/glw — Licence: CC-BY-4.0. "
            "See also Gilbert et al. (2018) Scientific Data for GLW methodology."
        ),
    },
    {
        "source": "FAO FAOSTAT",
        "used_for": "Annual livestock stocks / contextual exposure (long lag)",
        "licence": (
            "CC BY 4.0 + FAO Statistical Database Terms of Use. Attribute FAO; "
            "do not imply FAO endorsement or use to promote a commercial enterprise. "
            "(Supersedes older CC BY-NC-SA labelling on some legacy pages.)"
        ),
        "citation": (
            "FAO. 2026. FAOSTAT: Crops and livestock products / related livestock "
            "stock series used in this build. [Accessed for this build]. "
            "https://www.fao.org/faostat/ Licence: CC-BY-4.0."
        ),
    },
    {
        "source": "UN Comtrade (stub)",
        "used_for": "Trade connectivity scaffold — not in MVP live pipeline",
        "licence": (
            "UN copyright. Free visualisation / analytics and substantially "
            "transformed indicators permitted under UNSD re-dissemination policy; "
            "do not ship raw Comtrade microdata dumps in the public app bundle."
        ),
        "citation": (
            "UN Comtrade. Merchandise trade statistics. "
            "https://comtradeplus.un.org/ — see UNSD Policy on use and re-dissemination."
        ),
    },
]


METHODOLOGY_LITERATURE: list[dict[str, str]] = [
    {
        "topic": "Right-truncated reporting delay",
        "how_used": (
            "Likelihood for delay D with right truncation at analysis date T "
            "(discretised log-normal / NegBin; partial pooling)."
        ),
        "citation": (
            "Brookmeyer, R. & Gail, M. H. (1988). A method for obtaining short-term "
            "projections and lower bounds on the size of the AIDS epidemic. JASA. — "
            "Lawless, J. F. (2003). Statistical models and methods for lifetime data "
            "(truncation). — Outbreak nowcasting practice: e.g. Günther et al.; "
            "McGough, S. F. et al. (2020). Nowcasting by Bayesian Smoothing. "
            "PLOS Computational Biology."
        ),
    },
    {
        "topic": "Incomplete-count nowcasting",
        "how_used": (
            "Eventually-reportable remainder given reporting probability p_w; "
            "ascertainment prior kept explicit (not claimed identified from WAHIS alone)."
        ),
        "citation": (
            "Höhle, M. & an der Heiden, M. (2014). Bayesian nowcasting during the "
            "STEC O104:H4 outbreak in Germany, 2011. Biometrics. — "
            "Related: Bastos, L. S. et al.; McGough et al. (2020) on nowcasting "
            "incomplete epidemic counts."
        ),
    },
    {
        "topic": "CRPS forecast scoring / mixture weights",
        "how_used": "CRPS-weighted ensemble of NegBin GLM, damped Holt, seasonal climatology.",
        "citation": (
            "Gneiting, T. & Raftery, A. E. (2007). Strictly proper scoring rules, "
            "prediction, and estimation. JASA. — Hyndman, R. J. & Athanasopoulos, G. "
            "Forecasting: Principles and Practice (damped trend / seasonal benchmarks)."
        ),
    },
    {
        "topic": "Probability calibration (isotonic)",
        "how_used": "Isotonic calibration of early-warning scores on a later temporal window.",
        "citation": (
            "Zadrozny, B. & Elkan, C. (2002). Transforming classifier scores into "
            "accurate multiclass probability estimates. KDD. — "
            "Niculescu-Mizil, A. & Caruana, R. (2005). Predicting good probabilities "
            "with supervised learning. ICML."
        ),
    },
    {
        "topic": "Feature attributions (SHAP / occlusion)",
        "how_used": "Tree SHAP or occlusion Δ vs training median for Investigate explanations.",
        "citation": (
            "Lundberg, S. M. & Lee, S.-I. (2017). A unified approach to interpreting "
            "model predictions. NeurIPS."
        ),
    },
    {
        "topic": "Effective independent evidence (n_eff)",
        "how_used": "Clustered media/official weights → Kish-style effective sample size gates.",
        "citation": (
            "Kish, L. (1965). Survey Sampling. Wiley. "
            "(Effective sample size under correlated weights; adapted here to "
            "independence clusters, not survey design strata.)"
        ),
    },
    {
        "topic": "ERA5 reanalysis (climate covariates)",
        "how_used": "Environmental suitability / anomaly features with ingestion lag.",
        "citation": (
            "Hersbach, H. et al. (2020). The ERA5 global reanalysis. "
            "Quarterly Journal of the Royal Meteorological Society, 146, 1999–2049. "
            "https://doi.org/10.1002/qj.3803"
        ),
    },
]


def _source_table() -> ui.Tag:
    rows = [
        ui.tags.tr(
            ui.tags.td(ui.tags.strong(r["source"])),
            ui.tags.td(r["used_for"]),
            ui.tags.td(r["licence"]),
            ui.tags.td(r["citation"]),
        )
        for r in DATA_SOURCE_ROWS
    ]
    return ui.tags.table(
        {"class": "ahr-legal-table table table-sm table-bordered"},
        ui.tags.thead(
            ui.tags.tr(
                ui.tags.th("Source"),
                ui.tags.th("Used for"),
                ui.tags.th("Licence / terms (summary)"),
                ui.tags.th("Suggested citation"),
            )
        ),
        ui.tags.tbody(*rows),
    )


def _method_table() -> ui.Tag:
    rows = [
        ui.tags.tr(
            ui.tags.td(ui.tags.strong(r["topic"])),
            ui.tags.td(r["how_used"]),
            ui.tags.td(r["citation"]),
        )
        for r in METHODOLOGY_LITERATURE
    ]
    return ui.tags.table(
        {"class": "ahr-legal-table table table-sm table-bordered"},
        ui.tags.thead(
            ui.tags.tr(
                ui.tags.th("Method / principle"),
                ui.tags.th("How used in this pilot"),
                ui.tags.th("Key literature (cite when discussing the method)"),
            )
        ),
        ui.tags.tbody(*rows),
    )


def data_licensing_section() -> ui.Tag:
    """Cross-cutting licences, citations and no-endorsement disclaimer."""
    return ui.div(
        {"class": "ahr-licensing mt-4"},
        ui.h3("Data sources, licences & citations"),
        ui.p(
            "This Datathon prototype reuses existing international datasets. It does ",
            ui.tags.strong("not"),
            " claim ownership of those data and does ",
            ui.tags.strong("not"),
            " imply endorsement by WOAH, FAO, WHO, CIRAD, ECMWF, the European Commission, "
            "ISID, Boston Children's Hospital, or any other provider. Cite the primary "
            "sources below when referring to results or republishing derived figures."
        ),
        ui.div(
            {"class": "ahr-callout"},
            ui.p(
                ui.tags.strong("No endorsement: "),
                "Mentions of WOAH, FAO, WHO/EIOS, CIRAD, Copernicus/ECMWF, GDELT, "
                "BEACON, ProMED or HealthMap identify provenance only. Do not use "
                "organisational logos or present this app as an official product of "
                "those organisations.",
                class_="mb-0",
            ),
        ),
        ui.h4("Primary sources", class_="mt-3"),
        _source_table(),
        ui.h4("Repository / deploy hygiene", class_="mt-4"),
        ui.tags.ul(
            ui.tags.li(
                ui.tags.strong("WAHIS INFUR/SMR extracts "),
                "are cached under ",
                ui.tags.code("data/raw/"),
                " for reproducibility of this Datathon freeze — always cite WAHIS/WOAH."
            ),
            ui.tags.li(
                ui.tags.strong("PADI-web / BEACON / EIOS newsmap caches "),
                "under ",
                ui.tags.code("data/raw/"),
                " are derived snapshots; cite the live systems, not this cache as the source of record."
            ),
            ui.tags.li(
                ui.tags.strong("Sample / synthetic enrichment "),
                "(",
                ui.tags.code("data/sample/"),
                ") is labelled in provenance — never cite as real WAHIS or media."
            ),
            ui.tags.li(
                ui.tags.strong("Do not commit raw UN Comtrade dumps "),
                "if that stub is activated later; ship only derived scores."
            ),
        ),
        ui.p(
            ui.tags.small(
                "Full status table: docs/DATA_SOURCE_STATUS.md · provenance schema: "
                "docs/DATA_PROVENANCE.md · adapter licence fields stamped on each record."
            )
        ),
    )


def methodology_citations_section() -> ui.Tag:
    """Literature that principles / scoring methods draw on."""
    return ui.div(
        {"class": "ahr-licensing mt-4"},
        ui.h3("Methodology literature & principles"),
        ui.p(
            "The pilot implements standard epidemiological nowcasting / forecasting "
            "ideas; it is ",
            ui.tags.strong("not"),
            " a re-implementation of any single published pipeline. Cite the "
            "method families below when describing the maths (see also ",
            ui.tags.code("docs/METHODOLOGY.md"),
            ")."
        ),
        _method_table(),
        ui.p(
            ui.tags.small(
                "For submission PDFs, paste the data-source citation block from "
                "Data sources and add exact access dates for each frozen extract."
            )
        ),
    )
