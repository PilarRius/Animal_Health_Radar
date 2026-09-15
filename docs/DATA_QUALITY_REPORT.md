# Data Quality Report

**Mode:** synthetic sample corpus  
**Cut-off:** 2025-12-29  
**Generator seed:** 20250915

## Coverage

| Dimension | Assessment |
|-----------|------------|
| Temporal | Continuous weekly panel 2020–2025 for 20×2 entities |
| Spatial | Country-level primary; point lat/lon on events for maps |
| Disease | HPAI + ASF only (config-extensible) |
| Source | Official + media + aggregator + env + exposure present |
| Provenance | Ledger populated for ingested records |

## Known synthetic artefacts

- Perfect field completeness relative to real WAHIS (real data will have missing onset/suspicion).
- Intelligence systematically leads official publication by construction — optimistic for early warning demos.
- EIOS labelled `mock`.
- Latent ground truth exists (unlike reality) for scoring nowcasts offline.

## Metrics tracked in pipeline

`data/interim/data_quality.parquet` records issue counts from ingest (duplicates, timeline inconsistencies, missing availability, etc.). Re-run `scripts/ingest.py` after data changes and refresh this report.

## Human-readable follow-up

After first live WAHIS ingest, regenerate:

- missingness by field  
- duplicate / linkage rates  
- delay distributions by country × disease  
- source overlap matrix  
- country and temporal coverage plots under `reports/figures/`
