# Animal Health Radar — Technical Report

**WOAH International Datathon 2026 · Challenge 1**  
Early detection, nowcasting and short-term forecasting of animal-health events

**Data mode:** offline pilot (real WAHIS INFUR + SMR extracts; no WAHIS API calls)

---

## 1. Problem and proposition

Official surveillance (WAHIS) is essential but delayed and incomplete. Decision-makers therefore systematically understate risk at the leading edge of an epidemic if they only look at the latest published map.

Animal Health Radar separates three layers:

1. **Latent disease state** — what is plausibly happening  
2. **Observation / reporting process** — what has been officially published so far  
3. **Future process** — short-term evolution at 7 / 14 / 28 days  

The operational output is a calibrated investigation priority with explicit uncertainty, evidence provenance, and historical replay (“what would we have known then?”).

## 2. Data

### 2.1 Official backbone (real, offline)

| Layer | File | Role |
|-------|------|------|
| **INFUR** | `data/raw/infur_outbreaks_*.csv` | Outbreak-level Immediate Notification / Follow-Up Reports — primary observation process |
| **SMR** | `data/raw/smr_diseases_*.csv` | Six-Month Report semester status — covariates only, **not** outbreak counts |

INFUR and SMR use **different ID spaces**. Absence of INFUR reports does **not** imply absence of disease:

- When a situation is treated as **stable / endemic**, countries often stop event-driven INFUR and continue only on **SMR**.
- Some diseases are **not notifiable** via INFUR and appear (if at all) only on SMR.
- Some diseases **are** notifiable but endemic practice still under-uses INFUR.

SMR is therefore kept as **covariates + secondary validation** in Forecast & Replay (semester present / outbreak totals knowable after as-of), never mixed into the INFUR weekly outbreak series. Details: `docs/WAHIS_INFUR_SMR_DROP.md`.

**No WAHIS API calls** are made. Reproducibility depends on these local extracts.

### 2.2 Enrichment

| Source | Pilot status |
|--------|----------------|
| **BEACON** | **Real** public API (`api.beaconbio.org/public/report`), cached in `data/raw/beacon/` |
| **PADI-web** | **Real** public JSON listing (`padi-web.cirad.fr/en/articles/api/`), cached in `data/raw/padiweb/` |
| **EIOS** | **Real** recent public WHO newsmap (`portal.who.int/pandemichub/newsmap/tunnel`); optional full portal export |
| GDELT / ProMED / HealthMap | Labelled sample overlays unless replaced |
| ERA5 / WorldClim / GLW4 / FAOSTAT | Labelled sample overlays unless replaced |

EMPRES-i is **skipped** in pilot mode because it largely republishes WAHIS INFUR.

Details: `docs/EIOS_BEACON_ACCESS.md`.

### 2.3 Scope

- Diseases: **HPAI**, **ASF**  
- Spatial panel: 20 EuFMD / neighbourhood countries (see `config/countries.yaml`)  
- Temporal resolution: country × disease × week (Monday weeks)  
- Knowledge cut-off: configured `time.data_cutoff`

## 3. Methods

### 3.1 Signal normalisation and linkage

All sources map to a canonical event/signal schema with mandatory `available_from` (point-in-time knowability). Official INFUR outbreaks are de-duplicated; a reporting triangle supports right-truncated delay estimation.

### 3.2 Reporting delay

Right-truncation-corrected log-normal / negative-binomial delay from onset (or best reference date) to INFUR `submissionDate`, with partial pooling by disease and surveillance-capacity tier.

### 3.3 Latent nowcast

Negative-binomial completion of the right-truncated triangle + explicit ascertainment prior (tier × disease) + local-level smoothing across a 12-week window. **Reporting gap** = hidden share of estimated latent burden (4-week aggregate for stability).

### 3.4 Early warning

Calibrated gradient-boosting (isotonic) predicting emergence / escalation of **officially visible** activity within 28 days, vs baselines. Target is visibility/escalation in the official record — not latent confirmation.

### 3.5 Forecast

CRPS-weighted ensemble (NegBin GLM, damped trend, seasonal climatology) at 7 / 14 / 28 days with predictive intervals.

### 3.6 Decision layer

Investigation priority blends early-warning probability, reporting gap, latent level, forecast growth and intelligence anomaly. Alert levels are threshold bands (operational placeholders pending cost-sensitive calibration).

## 4. Evaluation

Artefacts under `reports/validation/`:

- Early-warning discrimination / calibration (`early_warning_metrics.json`)  
- Forecast ensemble CRPS weights (`forecast_meta.json`)  
- Reporting-delay fits (`delay_summary.parquet`)  
- **Lead time** vs first INFUR notification after a quiet gap (`lead_time.json`)  

Critical rule: every retrospective score uses only information with `available_from ≤ as_of`.

### 4.1 Pilot snapshot (real INFUR, regenerate with `python scripts/evaluate.py`)

Typical latest run characteristics (values change when re-trained):

- ~47k panel-scoped INFUR outbreaks (HPAI + ASF) after offline normalisation  
- Early-warning test ROC-AUC ~0.7; PR-AUC lower (class imbalance)  
- Forecast CRPS ensemble weights favour damped trend / seasonal on this window  
- Lead-time cases are conservative (ALERT threshold); GDELT/ProMED/HealthMap remain sample-labelled while BEACON/PADI are real  


**INFUR caveat:** many Follow-Up rows lack the original Immediate Notification in the extract. Onset→submission gaps > 60 days are treated as unreliable for delay/burden weeks; the modelling reference falls back to submission week while true onset is retained in provenance extras.

## 5. Interface

Shiny for Python app (`shiny run app.py`):

1. **Intro** — problem, answer, demo path  
2. **Global Radar** — choropleth of model estimates  
3. **Investigate** — observed vs latent, timeline, why, counterfactuals, provenance  
4. **Forecast & Replay** — fan charts + historical as-of replay  
5. **Data sources** / **Methodology** — judge-facing documentation  

All map values are **MODEL ESTIMATES**, not confirmed outbreaks.

## 6. Reproducibility

```bash
# Requires Python ≥3.11 and offline INFUR/SMR files under data/raw/
pip install -r requirements.txt
python scripts/run_pipeline.py --app-as-of-only --n-as-of 52
python scripts/evaluate.py
shiny run app.py --host 127.0.0.1 --port 8000
```

Configuration: `config/config.yaml` (`project.data_mode: pilot`).

## 7. Limitations (honest)

1. Some enrichment signals remain synthetic (GDELT/ProMED/HealthMap); EIOS newsmap is real but recent-only — lead-time gains should be re-validated as feeds deepen.  

2. Ascertainment is a **prior**, not identified from WAHIS alone.  
3. Country panel is European-neighbourhood focused; global INFUR rows outside the panel are dropped.  
4. Alert thresholds are not yet optimised against WOAH false-alert cost preferences.  
5. Spatial unit is country-week; outbreak points are retained in interim for maps/provenance but models aggregate to countries.

## 8. Submission checklist

- [ ] Analytical pipeline (this repository)  
- [ ] This technical report  
- [ ] README with reproduction steps  
- [ ] `Open_Source_Sharing_Agreement_signed.pdf` at repo root (Team Leader)  
- [ ] Private GitHub + grant `diad-woah` read access by **31 October 2026**  
- [ ] No commits after the deadline  

---

*Animal Health Radar — reconstruct the gap between disease reality and disease visibility.*
