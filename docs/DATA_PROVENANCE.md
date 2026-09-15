# Data Provenance

Every ingested record carries a `SourceProvenance` stamp (`src/schemas/provenance.py`) with the fields required by prompt §61:

- source name
- URL / citation when permitted
- source record ID
- retrieval timestamp
- publication timestamp
- event / reference timestamp on the parent record
- source type and tier
- lineage (`derived_from`, `is_downstream_of_official`)
- independence cluster (`evidence_cluster`)
- realism (`real` | `synthetic` | `mock` | `derived`)

The ledger is written to `data/interim/provenance.parquet` by `scripts/ingest.py`.

EMPRES-i rows that republish WAHIS are marked downstream-of-official and share the official evidence cluster so they do not inflate independent evidence counts.
