# Data Source Status

Status of each source required by the master build prompt.  
**Legend:** `active` = adapter + sample wired into pipeline · `stub` = adapter interface only · `blocked` = no access / not in MVP.

**Licences & citations (canonical):** in-app **Data sources → Data sources, licences & citations**  
(`dashboard/licensing.py`, mirrored from the sibling TVI app’s licensing table pattern).  
Each adapter also stamps `licence` + `homepage` on provenance.

| Source | Status | Independence role | Licence (summary) | Notes |
|--------|--------|-------------------|-------------------|-------|
| WAHIS | active | Level 1 official | WOAH WAHIS public terms — attribute + URL | Primary observation (INFUR) |
| WAHIS_SMR | active | Official (covariates) | Same WOAH terms | Semester status; not INFUR events |
| EMPRES-i | active | Official cluster (downstream) | FAO EMPRES-i / FAO DB terms | Lineage marks WAHIS-derived; skipped in pilot |
| BEACON | active (real API) | Aggregator cluster | Public API — attribute BEACON | Cached under `data/raw/beacon/` |
| PADI-web | active (real API) | Media cluster | CIRAD PADI-web research/web tier | Cite Valentin et al. 2020; cache `data/raw/padiweb/` |
| GDELT | active | Media cluster | Open; must cite GDELT + URL | Volume/diversity/acceleration — not raw counts as probability |
| EIOS | active (real newsmap) | Aggregator | Public newsmap; portal exports restricted | WHO Pandemic Hub newsmap |
| ProMED | active (optional) | Media | ISID ProMED terms | Adapter present; not required for MVP |
| HealthMap | active (optional) | Media | HealthMap / BCH terms | Adapter present |
| ERA5 | active | Environmental | CC BY 4.0 (Copernicus CDS) + attribution notice | Cite Hersbach / CDS DOI |
| ERA5-Land | active | Environmental | Same Copernicus terms | Selective land variables |
| WorldClim | active | Environmental baseline | Academic/non-commercial; no redistribution w/o permission | Cite Fick & Hijmans 2017; not real-time weather |
| GLW4 | active | Exposure | CC BY 4.0 (FAO / Dataverse) | Gilbert et al. livestock layers; static reference year |
| FAOSTAT | active | Exposure / contextual | CC BY 4.0 + FAO Statistical DB Terms | Annual stocks; long `available_from` lag |
| UN Comtrade | stub | Connectivity | UN copyright; no raw microdata in app bundle | Scaffold only |
| Global Forest Watch | stub | Contextual | Provider terms when activated | Optional; disease-plausible use only |
| WTO SPS | stub | Contextual intelligence | Provider terms when activated | Restriction ≠ outbreak |
| Simulation Exercises | stub | Preparedness context | Provider terms when activated | Never treated as real outbreaks |

## MVP priority (prompt §75)

**In scope for first complete version:** WAHIS + intelligence (GDELT/PADI/BEACON) + ERA5 + GLW4 + early warning + latent nowcast + reporting gap + 7/14/28 forecast + uncertainty + historical replay + evaluation + Shiny.

Stubs must not block `scripts/run_pipeline.py`.
