# Data Source Status

Status of each source required by the master build prompt.  
**Legend:** `active` = adapter + sample wired into pipeline · `stub` = adapter interface only · `blocked` = no access / not in MVP.

| Source | Status | Independence role | Notes |
|--------|--------|-------------------|-------|
| WAHIS | active | Level 1 official | Primary observation process; sample synthetic events |
| EMPRES-i | active | Official cluster (downstream) | Lineage marks WAHIS-derived; no double count |
| BEACON | active | Aggregator cluster | Intelligence layer; sample signals |
| PADI-web | active | Media cluster | Event-based news extraction signals |
| GDELT | active | Media cluster | Abnormal volume, diversity, acceleration — not raw counts as probability |
| EIOS | active (mock) | Aggregator | Clean `EIOSAdapter`; data labelled `mock` |
| ProMED | active (optional) | Media | Adapter present; not required for MVP |
| HealthMap | active (optional) | Media | Adapter present |
| ERA5 | active | Environmental | Weekly country aggregates in sample |
| ERA5-Land | active | Environmental | Selective land variables |
| WorldClim | active | Environmental baseline | Climatology only — never treated as real-time weather |
| GLW4 | active | Exposure | Contextual livestock density (static reference year) |
| FAOSTAT | active | Exposure / contextual | Annual stocks; long `available_from` lag |
| UN Comtrade | stub | Connectivity | Adapter scaffold; trade as exposure/network, not causal |
| Global Forest Watch | stub | Contextual | Optional; disease-plausible use only |
| WTO SPS | stub | Contextual intelligence | Restriction ≠ outbreak |
| Simulation Exercises | stub | Preparedness context | Never treated as real outbreaks |

## MVP priority (prompt §75)

**In scope for first complete version:** WAHIS + intelligence (GDELT/PADI/BEACON) + ERA5 + GLW4 + early warning + latent nowcast + reporting gap + 7/14/28 forecast + uncertainty + historical replay + evaluation + Shiny.

Stubs must not block `scripts/run_pipeline.py`.
