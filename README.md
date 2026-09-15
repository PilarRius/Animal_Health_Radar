# Animal Health Radar

Probabilistic evidence-fusion and latent-state estimation for early detection, nowcasting and short-term forecasting of animal-health events under incomplete and delayed surveillance (WOAH International Datathon 2026, Challenge 1).

**This is not “an AI outbreak detector.”** Numerical risks come from a statistical/ML pipeline that separates the **disease process** from the **observation/reporting process**.

## Scientific concept

```
TRUE / LATENT DISEASE STATE
        ↓
SURVEILLANCE + DETECTION
        ↓
REPORTING / CONFIRMATION
        ↓
OFFICIAL OBSERVATION (e.g. WAHIS)
```

The system estimates what has already happened, what is probably happening now, how much may be unobserved, how likely the situation is to become officially visible, and the 7/14/28-day trajectory — with explicit uncertainty.

## Architecture

```
DATA SOURCES (adapters under src/ingestion/)
        ↓
RAW / SAMPLE INGESTION          scripts/ingest.py
        ↓
NORMALISATION + ENTITY RESOLUTION + AS-OF SEMANTICS
        ↓
FEATURE STORE                   scripts/build_features.py
        ↓
┌───────────────────┬────────────────────┬────────────────────┐
│ Reporting delay   │ Latent nowcast     │ Early warning      │
│ + forecast        │                    │ + calibration      │
└───────────────────┴────────────────────┴────────────────────┘
        ↓                           scripts/train.py
ALERT / PREDICTION OBJECTS
        ↓                           scripts/evaluate.py
METRICS + MODEL CARDS
        ↓
PYTHON SHINY APP                shiny run app.py
  (loads precomputed parquet only — no fitting in reactives)
```

Modelling code lives in `src/models/`. The Shiny UI lives in `app/` and only reads processed artefacts.

## Status of this repository

| Layer | Status |
|-------|--------|
| Synthetic sample corpus (HPAI + ASF) | Ready (`data/sample/`, labelled `synthetic`) |
| Ingest + linkage + feature store | Ready |
| Reporting-delay, nowcast, early-warning, forecast | Trained offline |
| Shiny app (Radar / Investigate / Forecast+Replay) | Ready (loads precomputed parquet) |
| Live WAHIS pilot dump | **Not in repo** — switch `project.data_mode` when available |

## Installation

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

## Pipeline

```bash
# Full offline run (sample data)
python scripts/run_pipeline.py

# Or step-by-step
python scripts/ingest.py
python scripts/build_features.py
python scripts/train.py --app-as-of-only
python scripts/evaluate.py
```

### What each script writes

| Script | Writes |
|--------|--------|
| `scripts/ingest.py` | `data/interim/` — `events.parquet`, `signals.parquet`, `covariates.parquet`, `canonical_events.parquet`, `linked_events.parquet`, `linkage_clusters.parquet`, `provenance.parquet`, `reporting_triangle.parquet`, `evidence_sets.parquet`, `source_catalogue.parquet`, `data_quality.parquet`, `ingest_manifest.json` |
| `scripts/build_features.py` | `data/processed/` — `feature_store.parquet`, `feature_availability.parquet`, `design_matrix.parquet`, `early_warning_labels.parquet`, `forecast_targets.parquet`, `observed_final_series.parquet`, `features_manifest.json` |
| `scripts/train.py` | `data/processed/predictions.parquet`, `alerts.parquet`, `explanations.json`, `nowcast_latest.parquet`, `train_manifest.json`; models under `data/processed/models/` (`delay_model.pkl`, `early_warning_model.pkl`, `forecast_model.pkl`, metrics/importance sidecars) |
| `scripts/evaluate.py` | `reports/validation/metrics.json`, `reports/validation/metrics.csv` |
| `scripts/run_pipeline.py` | Runs the stages above in order (ingest → features → train → evaluate) |

If sample CSVs are missing, ingest regenerates them via `src/ingestion/sample_generator.py` into `data/sample/` (all labelled synthetic).

### Key artefacts the app reads

| Path | Role |
|------|------|
| `data/processed/predictions.parquet` | Master country × disease × as-of table (EW, latent, gap, forecasts) |
| `data/processed/alerts.parquet` | Alert objects for Investigate / radar |
| `data/processed/explanations.json` | Why-this-alert + counterfactual ablations |
| `data/processed/nowcast_latest.parquet` | Latest nowcast panel (optional) |

## Shiny application

```bash
shiny run app.py
```

Screens:

1. **Global Radar** — investigation priority / latent activity / reporting gap / forecasts (as-of aware)
2. **Investigate** — KPIs, observed vs latent, Why this alert, counterfactual family ablations
3. **Forecast & Replay** — 7/14/28 fan-style intervals and historical as-of replay table

All UI numbers are **MODEL ESTIMATES**. The banner states the data mode.

## Tests

Leakage suite (as-of filtering, no future publications/features, temporal split discipline):

```bash
# Disable broken third-party pytest plugins if needed (e.g. langsmith)
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest tests/leakage -q
```

On PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/leakage -q
```

## Configuration

- `config/config.yaml` — paths, horizons, splits, ascertainment priors
- `config/diseases.yaml` — HPAI / ASF (extensible)
- `config/countries.yaml` — panel countries
- `config/thresholds.yaml` — operational alert bands (not claimed epidemiologically optimal)

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/DATA_INVENTORY.md`](docs/DATA_INVENTORY.md) | What data exists in the repo |
| [`docs/DATA_SOURCE_STATUS.md`](docs/DATA_SOURCE_STATUS.md) | Adapter status (active / stub / mock) |
| [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) | Field meanings |
| [`docs/CANONICAL_SCHEMA.md`](docs/CANONICAL_SCHEMA.md) | Event / signal / provenance contracts |
| [`docs/TARGET_DEFINITION.md`](docs/TARGET_DEFINITION.md) | EW / nowcast / forecast targets |
| [`docs/LEAKAGE_POLICY.md`](docs/LEAKAGE_POLICY.md) / [`LEAKAGE_AUDIT.md`](docs/LEAKAGE_AUDIT.md) | As-of rules |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) / [`INITIAL_MODEL_DESIGN.md`](docs/INITIAL_MODEL_DESIGN.md) | Methods |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Modelling decision log |
| [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) / [`VALIDATION.md`](docs/VALIDATION.md) | Card + metrics notes |
| [`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md) | §61 provenance fields |

## Limitations

- Current metrics are on a **synthetic** corpus designed so media leads official publication — optimistic for early-warning demos.
- Ascertainment is a **config prior**, not estimated from WAHIS alone.
- Absolute probabilities are not transferable to live surveillance without refitting on real pilot data.

## Licence / provenance

Preserve source provenance (§61): source, URL, record id, retrieval/publication/event timestamps, source type, lineage, independence cluster. EMPRES-i records downstream of WAHIS are not double-counted.
