# Data Inventory

**Project:** Animal Health Radar (WOAH International Datathon 2026, Challenge 1)  
**Inventory date:** 2026-09-15  
**Data mode:** `sample` (fully synthetic, offline)

## Repository status

| Location | Status | Notes |
|----------|--------|-------|
| Pilot / live WAHIS files | **Not present** | No official WOAH pilot dump in this repo yet |
| `data/sample/` | Present | Synthetic corpus for offline development |
| `data/interim/` | Present | Canonicalised ingest + linkage outputs |
| `data/processed/` | Partial | Feature store built; model prediction tables pending train stage |
| `data/raw/` | Empty placeholder | Live downloads would land here under caching rules |
| `data/external/` | Empty placeholder | Static external layers (GLW4 rasters, etc.) |

## Decision

Until a real pilot WAHIS extract is supplied, the pipeline runs exclusively on the **labelled synthetic corpus** produced by `src/ingestion/sample_generator.py`. Every record carries `realism = synthetic` (or `mock` for EIOS). The UI and reports must surface this label.

## Sample corpus summary

| File | Adapter | Rows (approx.) | Role |
|------|---------|----------------|------|
| `wahis_events_sample.csv` | wahis | 6,330 | Official observation process (ground truth for evaluation of *visibility*, not latent truth) |
| `empresi_events_sample.csv` | empresi | 4,893 | Downstream-of-WAHIS + limited independent field signals |
| `gdelt_daily_sample.csv` | gdelt | 57,598 | Media volume / diversity / acceleration signals |
| `padiweb_articles_sample.csv` | padiweb | 26,246 | News extraction intelligence |
| `promed_posts_sample.csv` | promed | 1,231 | Optional curated intelligence |
| `healthmap_alerts_sample.csv` | healthmap | 1,4035 | Optional aggregator alerts |
| `beacon_signals_sample.csv` | beacon | 8,975 | Structured epidemic intelligence |
| `eios_board_items_mock.csv` | eios | 1,955 | **Mock** stand-in for inaccessible EIOS |
| `era5_weekly_sample.csv` | era5 | 6,260 | Environmental covariates (weekly country aggregates) |
| `era5land_weekly_sample.csv` | era5_land | 6,260 | Land-surface complements |
| `worldclim_climatology_sample.csv` | worldclim | 240 | Climatological baseline (not real-time weather) |
| `glw4_livestock_density_sample.csv` | glw4 | 120 | Host exposure (2020-style static context) |
| `faostat_livestock_annual_sample.csv` | faostat | 360 | Country livestock stocks (long availability lag) |
| `_ground_truth_latent_weekly.csv` | truth | 12,520 | Hidden latent process — **evaluation only**; leakage tests forbid feature use |

**Panel:** 20 countries × HPAI + ASF × weekly, 2020-01-06 → 2025-12-29 (seed `20250915`).

## Interim products (post-ingest)

Produced by `scripts/ingest.py`:

- `events.parquet`, `linked_events.parquet`, `canonical_events.parquet`
- `signals.parquet`, `covariates.parquet`
- `provenance.parquet` (section 61 fields)
- `reporting_triangle.parquet` (onset week × available week counts)
- `linkage_clusters.parquet`, `evidence_sets.parquet`
- `data_quality.parquet`, `source_catalogue.parquet`

## Processed products (post-features)

Produced by `scripts/build_features.py`:

- Point-in-time feature store + design matrix under as-of grid
- Early-warning labels and forecast targets attached to design rows

Model outputs (`predictions.parquet`, `alerts.parquet`) are produced by `scripts/train.py` once modelling stage completes.

## Generative mechanism (sample only)

1. Latent weekly counts via spatio-temporal Hawkes-like process (seasonality, climate suitability, livestock, self-excitation, spatial spillover).
2. Detection via country-specific ascertainment (surveillance capacity tier).
3. Reporting delays via log-normal onset→notification (+ publication lag), inducing right-truncation at corpus cut-off.
4. Media/intelligence generated from latent layer with short lead — the exploitable early-warning signal.

## Gaps / next data action

When real pilot WAHIS arrives:

1. Place under `data/raw/wahis/` without renaming originals.
2. Map fields in `src/ingestion/wahis.py` (do not assume sample column names).
3. Re-run inventory + data-quality report.
4. Keep sample mode available for CI via `project.data_mode: sample`.
