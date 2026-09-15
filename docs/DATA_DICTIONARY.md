# Data Dictionary

## Conventions

- Dates are ISO `YYYY-MM-DD`.
- `available_from` = earliest date the pipeline may use the record for prediction (knowability).
- `reference_date` / `reference_week` = when the underlying epidemiological activity is attributed (event time).
- `entity_key` = `{ISO3}|{DISEASE}` (e.g. `POL|ASF`).
- `realism` ∈ {`real`, `synthetic`, `mock`, `derived`}.

## WAHIS sample columns → canonical

| Sample column | Canonical field | Semantics |
|---------------|-----------------|-----------|
| `event_id` | `event_id` / `source_event_id` | Source identity |
| `disease_code` | `disease` | HPAI / ASF |
| `disease` | `disease_raw` | Long WAHIS disease string |
| `iso3` | `country_iso3` | ISO 3166-1 alpha-3 |
| `start_date` | `onset_date` | Event time (onset) |
| `date_of_suspicion` | `suspicion_date` | Observation chain |
| `date_of_confirmation` | `confirmation_date` | |
| `date_of_notification` | `notification_date` | |
| `date_of_publication` | `publication_date` → `available_from` | Knowability |
| `outbreaks`, `cases`, `deaths`, … | same | Magnitude |
| `data_realism` | `realism` | Must remain `synthetic` for sample |

**Rule:** Never substitute `publication_date` for `onset_date`.

## Provenance ledger (`provenance.parquet`)

| Field | Meaning |
|-------|---------|
| `provenance_id` | Fingerprint |
| `record_id` | Source record ID |
| `source_name` | e.g. WAHIS |
| `source_type` / `source_tier` | Epistemic class |
| `evidence_cluster` | Independence cluster |
| `published_at` | Public release |
| `available_from` | As-of gate |
| `retrieved_at` | Pipeline fetch/generation time |
| `url`, `citation`, `licence` | Traceability |
| `derived_from` | Lineage (EMPRES-i ← WAHIS) |
| `is_downstream_of_official` | Double-count guard |
| `realism`, `reliability` | Quality |

## Feature families (design matrix)

| Family | Example features | Ablatable |
|--------|------------------|-----------|
| `temporal_anomaly` | EWMA z, rolling means, acceleration | yes |
| `spatial_risk` | neighbour-weighted activity | yes |
| `environmental` | suitability, temp/precip anomalies | yes |
| `livestock_exposure` | host density, national stock | yes |
| `intelligence` | fused anomaly, source diversity | yes |
| `historical_baseline` | seasonal climatology | yes |
| `reporting_behaviour` | expected delay, P(reported) | yes |

## Model output tables (post-train)

### `predictions.parquet`

`as_of_date`, `country`, `disease`, early-warning fields, latent/observed/gap, delay, forecasts 7/14/28 ± intervals, `confidence`, `model_version`.

### `alerts.parquet`

`alert_id`, location keys, `as_of_date`, score/probability/`alert_level`, `first_signal_date`, `lead_time`, `top_evidence`, `model_version`.
