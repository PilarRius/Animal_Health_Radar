# Methodology (detailed)

This document is the scientific defence of **Animal Health Radar**. Configuration
defaults below match `config/config.yaml` and `config/thresholds.yaml` as of the
pilot build. Code references: `src/models/delay.py`, `nowcast.py`,
`early_warning.py`, `forecast.py`, `ensemble.py`, `src/alerts/builder.py`,
`src/linkage/independence.py`.

---

## 0. Generative story

\[
\underbrace{\text{latent disease process}}_{N_w^{\text{true}}}
\;\xrightarrow{\text{ascertainment } a}\;
\underbrace{\text{eventually reportable}}_{N_w}
\;\xrightarrow{\text{delay } D}\;
\underbrace{\text{officially visible at } T}_{O_w(T)}
\]

Four model families answer four different questions and are kept **separate**
on purpose (no single black-box that conflates epidemiology with administration).

| # | Family | Question |
|---|--------|----------|
| 1 | Reporting delay | How long until an event becomes knowable? |
| 2 | Latent nowcast | What is happening *now*, given incomplete observation? |
| 3 | Early warning | Will *official visibility* appear or escalate soon? |
| 4 | Forecast | What is the short-term distribution of eventually reported burden? |

**As-of discipline.** For any score stamped with cut-off \(T\), only records
with \( \texttt{available\_from} \le T \) may enter features or parameters.
Temporal train / calibration / test splits; no random row shuffles.
Automated checks: `tests/leakage/`.

**Official observation.** Primary timed series = WAHIS **INFUR**
(Immediate Notification / Follow-Up). **SMR** (Six-Month Report) is a semester
status covariate and secondary validation layer — never mixed into the INFUR
weekly outbreak curve (see `docs/WAHIS_INFUR_SMR_DROP.md`).

---

## 1. Reporting delay model

### 1.1 Object

Delay \(D\) = days from **reference date** \(t\) (onset / best event time) to
**knowability** (submission / publication that sets `available_from`).

At analysis date \(T\), an outbreak with reference \(t\) appears in the data
**only if** \( D \le T - t \) (right truncation). Ignoring truncation makes
fitted delays too short and nowcasts too optimistic.

### 1.2 Truncated likelihood

For observations \(\{(t_i, d_i)\}\) knowable by \(T\):

\[
L(\theta) = \prod_i \frac{f(d_i \mid \theta)}{F(T - t_i \mid \theta)}
\]

where \(f\) is the delay pmf/pdf and \(F\) the cdf.

### 1.3 Families (AIC picks the winner per group)

**Discretised log-normal** with parameters \((\mu, \sigma)\):

\[
F_{\text{LN}}(d) = \Phi\!\left(\frac{\log(d+0.5)-\mu}{\sigma}\right),
\quad
f_{\text{LN}}(d) = F_{\text{LN}}(d) - F_{\text{LN}}(d-1)^+
\]

**Negative binomial** with mean \(\mu\) and dispersion \(\alpha\)
(\(n = 1/\alpha\), \(p = n/(n+\mu)\)):

\[
D \sim \mathrm{NB}(n, p),\qquad
\mathbb{E}[D]=\mu,\quad \mathrm{Var}(D)=\mu + \alpha\mu^2
\]

### 1.4 Partial pooling

Groups: `(disease, surveillance_capacity_tier)`. Fit group → shrink toward
disease-level fit → shrink toward global fit with weight

\[
w = \frac{n}{n + \kappa},\qquad \kappa = 40
\]

(implementation: `_SHRINKAGE_KAPPA` in `delay.py`).

### 1.5 Operational parameters

| Parameter | Config key | Pilot value |
|-----------|------------|-------------|
| Max recoverable delay | `nowcast.max_delay_days` | 90 days |
| Delay refit cadence | `nowcast.delay_refit_interval_weeks` | 8 weeks |
| Panel frequency | `time.panel_frequency` | `W-MON` |

From a fit, the nowcast uses reporting probability for reference week \(w\):

\[
p_w(T) = F\!\bigl(T - t_w \mid \hat\theta\bigr)
\]

floored by `nowcast.min_reporting_probability` (= **0.25**) to avoid IPW explosions.

---

## 2. Latent nowcast

### 2.1 Separating two unknowns

1. **Eventually reportable** count \(N_w\) for reference week \(w\)  
2. **Never reported** mass via ascertainment \(a\) (prior, not identifiable from WAHIS alone)

### 2.2 Unreported remainder (NegBin posterior predictive)

Let \(O_w\) = burden for week \(w\) already visible at \(T\), and \(p_w\) as above.
With Gamma\((a_0,b_0)\) prior on the weekly rate and Poisson reporting, the
not-yet-reported remainder has

\[
U_w \mid O_w \sim \mathrm{NB}\!\left(
  r = a_0 + O_w,\;
  q = \frac{b_0 + p_w}{b_0 + 1}
\right),
\qquad
\mathbb{E}[U_w] = (a_0 + O_w)\,\frac{1-p_w}{b_0 + p_w}
\]

\[
\hat N_w = O_w + U_w
\]

As \(a_0,b_0 \to 0\), \(\mathbb{E}[\hat N_w] \to O_w / p_w\) (classical IPW).

### 2.3 Ascertainment prior (explicit)

\[
a \sim \mathrm{Beta}(\alpha_{\text{tier}}, \beta_{\text{tier}}) \cdot m_{\text{disease}},
\qquad
\text{latent}_w = \frac{\hat N_w}{a}
\]

| Tier | \(\alpha\) | \(\beta\) | Prior mean |
|------|------------|-----------|------------|
| high | 22 | 3 | ≈ 0.88 |
| medium | 16 | 5 | ≈ 0.76 |
| low | 10 | 8 | ≈ 0.56 |

Disease multipliers: HPAI \(m=1.00\), ASF \(m=0.92\) (`ascertainment.disease_multiplier`).

### 2.4 Reporting gap

\[
\text{gap}_w = \frac{\widehat{\text{hidden}}_w}{\widehat{\text{latent}}_w}
= \frac{\text{latent}_w - O_w^{\text{(scaled)}}}{\text{latent}_w}
\]

Bands (`thresholds.yaml`): minor ≥ 0.25, moderate ≥ 0.50, severe ≥ 0.72.

### 2.5 Temporal smoothing

Independent week-wise \(\hat N_w\) are noisy when \(p_w\) is small. A **local-level
(random-walk) state-space** model on the log scale, with per-week Monte-Carlo
variance as observation noise, is smoothed by **Rauch–Tung–Striebel** recursions
over `nowcast.nowcast_window_weeks` (= **12**). Predictive spread still comes from
MC draws (`horizons.mc_draws` = **800**).

### 2.6 Uncertainty propagated

1. Sampling of \(U_w\) (NB posterior predictive)  
2. Uncertainty in \(p_w\) (Beta perturbation keyed to delay sample size)  
3. Ascertainment prior draws  

**Not** propagated: structural misspecification of the delay family; corpus coverage gaps.

---

## 3. Early warning

### 3.1 Target (official visibility — not “latent outbreak confirmed”)

Horizon \(H =\) `early_warning.label_horizon_days` (= **28**).  
Run-rate \(\hat r_T\) = visible weekly rate over `run_rate_weeks` (= **8**).  
Escalation factor \(\phi =\) `escalation_factor` (= **1.5**).

\[
Y_T = \mathbf{1}\!\left[
  \text{official publications in }(T,\,T+H]
  \;\ge\;
  \max\!\bigl(1,\; \phi \cdot \hat r_T \cdot H/7\bigr)
\right]
\]

- Quiet entity → threshold = 1 → **emergence**  
- Already reporting → **escalation** beyond current run-rate  

Rows with incomplete label horizon (`label_observable = False`) are dropped.

### 3.2 Classifier

Primary: `early_warning.primary_model` = **gradient_boosting**
(`sklearn.ensemble.GradientBoostingClassifier` on the point-in-time design matrix).  
Alternative: logistic regression with standardisation.

Features: official history, intelligence anomalies, environment, exposure,
spatial spillover (kernel bandwidth `features.spatial_kernel_km` = **900 km**),
EWMA anomalies (`ewma_alpha` = **0.30**), rolling windows
`[2,4,8,13,26,52]` weeks, family availability lags
(`features.availability_lag_days`).

### 3.3 Temporal splits (no shuffle)

| Window | End date (pilot) | Role |
|--------|------------------|------|
| Train | `as_of ≤ 2025-06-30` | Fit classifier |
| Calibration | `2025-06-30 < as_of ≤ 2025-12-29` | Fit calibrator |
| Test | `as_of > 2025-12-29` | Metrics only |

### 3.4 Calibration

`calibration_method`: **isotonic** (alternative: Platt / none).  
Produces calibrated \(\hat\pi_T = \widehat{\Pr}(Y_T=1 \mid x_T)\).

### 3.5 Alert bands (operational — not epidemiology-optimal)

Applied to calibrated \(\hat\pi_T\) (`thresholds.yaml`):

| Level | Min probability | Action (config text) |
|-------|-----------------|----------------------|
| NONE | 0.00 | Routine monitoring |
| INFO | 0.08 | Log signal |
| WATCH | 0.20 | Increase passive sensitivity |
| ALERT | 0.40 | Targeted active surveillance |
| CRITICAL | 0.65 | Immediate verification |

Hysteresis: `deescalate_margin` = 0.05; `min_persistence_weeks` = 1.

### 3.6 Explanations

- **SHAP** (tree) on log-odds when available  
- Else **occlusion**: \(\Delta_j = f(x) - f(x_{[j\leftarrow \mathrm{median}]})\)  
- **Family counterfactuals**: re-score with all features in a family set to training medians  

Baselines that must be beaten before claiming value: seasonal, EWMA, CUSUM,
official-only / NegBin (see `docs/INITIAL_MODEL_DESIGN.md`).

---

## 4. Short-term forecast

### 4.1 Target

`forecast.target` = **`reported_final`**: count of outbreaks with reference week
inside the horizon that are **eventually** reported (scorable).  
Latent scale = that count / ascertainment mean when
`forecast.report_latent_scale: true` — labelled separately.

Horizons: **7 / 14 / 28** days. Quantiles:
`[0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]`; central interval level **0.90**.

### 4.2 Ensemble members

1. **NegBin GLM** (log link) on covariates + Fourier seasonality for the target week  
2. **Damped Holt trend** on \(\log(1+y)\) of the vintage-visible series with damping \(\phi\)  
3. **Seasonal climatology**: week-of-year mean from prior years  

### 4.3 CRPS weights

On a validation window **after** `forecast.train_end` (= **2025-06-30**):

\[
w_m \propto \exp\!\left(-\frac{\mathrm{CRPS}_m}{\tau\,\overline{\mathrm{CRPS}}}\right),
\qquad \tau = 0.5,\quad w_m \ge \texttt{min\_weight}=0.05
\]

Predictive distribution = **mixture of draws** (not average of quantiles).

### 4.4 Exceedance questions (`forecast_questions`)

- \(P(\text{count} \ge 1)\) — any new official visibility  
- \(P(\text{count} > c)\) with multipliers on disease weekly thresholds  
- \(P(\text{increase})\) vs current nowcast central estimate with relative margin **0.10**

---

## 5. Investigation priority (Radar composite)

Policy-weighted score in \([0,1]\) (weights sum to 1 — **not** estimated):

\[
\begin{aligned}
\text{IP} &=
0.34\,\hat\pi
+ 0.22\,\text{gap}
+ 0.20\,\bigl(1-e^{-\text{latent}/5}\bigr) \\
&\quad
+ 0.14\,\mathrm{clip}(\text{forecast growth},0,1)
+ 0.10\,\sigma(\text{intel})
\end{aligned}
\]

where \(\sigma\) is a logistic squashing of the intelligence anomaly.  
Bands: moderate ≥ 0.30, high ≥ 0.52, very high ≥ 0.72.

---

## 6. Evidence independence

Effective independent source count:

\[
n_{\mathrm{eff}} = \frac{\bigl(\sum_i w_i\bigr)^2}{w^{\top} R\, w}
\]

with reliability weights \(w_i\) and correlation matrix \(R\) from
`config/config.yaml: independence` (clusters: official, media, aggregator,
environmental, exposure; within-cluster correlations 0.55–0.95).

Gates (`thresholds.yaml`):  
`min_independent_clusters_for_alert` = **1.35**,  
`min_independent_clusters_for_critical` = **2.10**.

---

## 7. Historical replay & SMR secondary validation

Replay at as-of \(T\):

1. Reconstruct model state using only information with `available_from ≤ T`  
2. Record first WATCH / ALERT in the scored series  
3. Compare to **INFUR** final-vintage weeks before / after \(T\)  
4. INFUR lead time = \(T_{\text{official}} - T_{\text{model}}\) when a later INFUR week exists  
5. If INFUR is silent after \(T\), check **SMR** semester covariates
   (`smr_disease_present`, `smr_new_outbreaks`, `smr_total_outbreaks`) whose
   report `available_from > T` and whose semester overlaps / just-closes near \(T\)

SMR validates at **semester grain** only. Stable/endemic practice and
non-notifiable diseases often leave INFUR; see `docs/WAHIS_INFUR_SMR_DROP.md`.

---

## 8. What we do **not** claim

- “Hidden outbreak confirmed” from model scores alone  
- Ascertainment as an estimate from WAHIS  
- Alert thresholds as epidemiologically optimal  
- Day-level lead time from SMR  
- Transfer of pilot probabilities to another data regime without refit  

Language: *estimated latent activity*, *reporting gap*, *probability of elevated
official visibility*, *MODEL ESTIMATE*.

---

## 9. Literature & principles (cite when discussing methods)

The pilot adapts standard ideas; it is **not** a clone of any single published pipeline.
In-app table: **Methodology → Methodology literature & principles**.

| Topic | Key references |
|-------|----------------|
| Right-truncated reporting delay | Brookmeyer & Gail (1988); Lawless (2003); McGough et al. (2020) *Nowcasting by Bayesian Smoothing* |
| Incomplete-count nowcasting | Höhle & an der Heiden (2014) *Biometrics* |
| CRPS / ensemble weights | Gneiting & Raftery (2007); Hyndman & Athanasopoulos (*FPP*) |
| Isotonic calibration | Zadrozny & Elkan (2002); Niculescu-Mizil & Caruana (2005) |
| SHAP explanations | Lundberg & Lee (2017) NeurIPS |
| Effective independent evidence \(n_{\mathrm{eff}}\) | Kish (1965) *Survey Sampling* (adapted to independence clusters) |
| ERA5 covariates | Hersbach et al. (2020) QJRMS; CDS DOI 10.24381/cds.adbb2d47 |

**Data licences & suggested citations** (WAHIS, FAOSTAT CC BY 4.0, Copernicus, GDELT, PADI-web, GLW4, WorldClim, …):  
**Data sources → Data sources, licences & citations** and `dashboard/licensing.py`.

---

## 10. Related docs

- `docs/INITIAL_MODEL_DESIGN.md` — stack overview & baselines  
- `docs/TARGET_DEFINITION.md` — EW / forecast targets  
- `docs/DECISIONS.md` — decision log  
- `docs/MODEL_CARD.md` — limitations  
- `docs/TECHNICAL_REPORT.md` — submission narrative  
- `docs/WAHIS_INFUR_SMR_DROP.md` — INFUR vs SMR reporting behaviour  
- `docs/DATA_SOURCE_STATUS.md` — adapter status + licence summary  
- `dashboard/licensing.py` — canonical in-app citation table  
