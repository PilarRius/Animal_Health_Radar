# Decisions Log

Format per prompt §78.

---

## Decision: Weekly country × disease panel

**Reason:** Global event data are sparse; daily models unstable for many country–disease pairs.  
**Alternatives:** Daily; admin1 × week.  
**Scientific consequence:** Smooths within-week dynamics; appropriate for datathon demonstration scale.  
**Implementation:** `time.panel_frequency: W-MON` in `config/config.yaml`.

---

## Decision: Synthetic sample corpus until pilot WAHIS arrives

**Reason:** Repository contained no pilot files; development must stay reproducible offline.  
**Alternatives:** Block until data delivered; scrape live APIs.  
**Scientific consequence:** Results demonstrate methodology, not real-world performance claims.  
**Implementation:** `project.data_mode: sample`; all rows labelled `synthetic`/`mock`.

---

## Decision: Right-truncated parametric reporting delays

**Reason:** Naive empirical delays understate recent incompleteness and bias nowcasts downward.  
**Alternatives:** Empirical CDF without truncation; constant global delay.  
**Scientific consequence:** Honest uncertainty on hidden burden.  
**Implementation:** `src/models/delay.py`.

---

## Decision: Early-warning label = emergence or escalation within 28 days

**Reason:** Pure “any future WAHIS row” is trivial in endemic seasons; pure emergence ignores intensification.  
**Alternatives:** Fixed count threshold; latent exceedance (unobservable for supervised training).  
**Scientific consequence:** One coherent supervised target across quiet and active regimes.  
**Implementation:** `early_warning` block in config + `build_early_warning_labels`.

---

## Decision: Ascertainment as explicit Beta prior by surveillance tier

**Reason:** P(ever detected) is not identifiable from official data alone.  
**Alternatives:** Assume ascertainment = 1; estimate jointly without identification strategy.  
**Scientific consequence:** Latent scale is assumption-dependent and labelled as such.  
**Implementation:** `ascertainment` in `config/config.yaml`.

---

## Decision: Prefer interpretable ensemble forecast over deep sequence models

**Reason:** Prompt priority on scientific defensibility and explainability within datathon timeline.  
**Alternatives:** LSTM/Transformer.  
**Scientific consequence:** Clear failure modes; CRPS-weighted members.  
**Implementation:** NegBin GLM + damped trend + seasonal climatology.

---

## Decision: EMPRES-i in official evidence cluster

**Reason:** Often republishes WAHIS; counting both inflates evidence.  
**Alternatives:** Treat as independent Level 2.  
**Scientific consequence:** Independence discounting within cluster.  
**Implementation:** `is_downstream_of_official` + independence config.

---

## Decision: SMR as secondary validation, never as INFUR outbreaks

**Reason:** Stable/endemic framing and non-notifiable (or notifiable-but-endemic) diseases often leave INFUR silent; Members may only update on Six-Month Reports. Ignoring SMR makes quiet-INFUR cases look like false alarms.  
**Alternatives:** INFUR-only evaluation; merge SMR counts into weekly outbreak series.  
**Scientific consequence:** Forecast & Replay can show semester-level supporting validation after model alerts without claiming day-level INFUR lead time or double-counting ID spaces.  
**Implementation:** `smr_*` covariates + replay story step 6; documented in `docs/WAHIS_INFUR_SMR_DROP.md`.
