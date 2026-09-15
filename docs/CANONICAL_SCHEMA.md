# Canonical Schema

## Unit of analysis

Primary panel: **country × disease × week** (`entity_key = ISO3|DISEASE`).  
Configurable via `config/config.yaml` → `time.panel_frequency` (`W-MON`). Admin1 / event-level supported later when density permits.

## Record types

| Type | Module | Purpose |
|------|--------|---------|
| `CanonicalEvent` | `src/schemas/canonical.py` | Disease-activity assertion from any source |
| `SignalRecord` | same | Non-event quantitative intelligence/env signals |
| `CovariateRecord` | same | Environmental / exposure / contextual covariates |
| `SourceProvenance` | `src/schemas/provenance.py` | Section 61 provenance stamp |

## CanonicalEvent (minimum fields)

Identity: `event_id`, `canonical_event_id`, `source_event_id`  
What: `disease`, `disease_raw`, `species`, `host_category`  
Where: `country_iso3`, `admin1`, `latitude`, `longitude`, `location_precision`  
When (never silently substituted): `onset_date`, `suspicion_date`, `confirmation_date`, `notification_date`, `publication_date`  
Knowability: `available_from` (publication / release date that gates as-of use)  
Magnitude: `outbreaks`, `cases`, `deaths`, `susceptible`, `killed_disposed`  
Epistemics: `confirmation_status`, `source_type`, `source_tier`, `evidence_cluster`, `is_downstream_of_official`, `realism`, `reliability`

Raw source columns are preserved in source-specific tables / provenance; normalisation never destroys originals.

## Source provenance (prompt §61)

Every external signal retains:

- `source_name`
- `url` / citation when permitted
- `record_id` (source record ID)
- `retrieved_at`
- `published_at`
- event / reference timestamp on the parent record
- `source_type`, `source_tier`
- lineage via `derived_from` / `is_downstream_of_official`
- `evidence_cluster` (independence cluster)

## Output contracts

| Object | Question answered |
|--------|-------------------|
| `NowcastObject` | What is probably happening now, and how much is invisible? |
| `ForecastObject` | Where is this going over 7/14/28 days, with what uncertainty? |
| `AlertObject` | Should a human look, why, and on what evidence? |

See `src/schemas/outputs.py`. Numeric fields are model-produced only — never authored for display.
