# Initial Model Design

## Core principle

\[
\text{Latent disease state}_t \;\rightarrow\; \text{Detection} \;\rightarrow\; \text{Reporting delay} \;\rightarrow\; \text{Official observation}
\]

Models estimate (A) latent activity, (B) observation/reporting process, (C) short-term future latent/reported trajectory.

## Component stack

| Component | Approach | Why |
|-----------|----------|-----|
| Reporting delay | Truncated log-normal / NegBin MLE with partial pooling by disease × surveillance tier | Avoids optimistic short-delay bias from right-truncation |
| Latent nowcast | Delay-adjusted IPW / state-space style reconstruction of recent weeks + ascertainment prior | Transparent; preferred over black-box NN |
| Early warning | Seasonal / EWMA / CUSUM / NB baselines → calibrated GBM or logistic on fused features | Baselines first; main model probabilistic & calibrated |
| Forecast | Ensemble: NegBin GLM + damped trend + seasonal climatology; CRPS weights | Interpretable; horizons 7/14/28 |
| Calibration | Isotonic or Platt on temporal calibration window | No leakage into test |
| Independence | Evidence clusters + effective independent source count | Prevents 20 articles ≠ 20 outbreaks |

## Baselines (required before claims)

1. Seasonal historical baseline  
2. EWMA anomaly  
3. CUSUM  
4. Poisson / NegBin regression  
5. Gradient boosting (if density supports)

## Alert bands (display only until calibrated)

Configured in `thresholds.yaml` (operational labels: NONE → CRITICAL). Prompt’s 0–40 / 40–60 / 60–80 / 80–100 STABLE/WATCH/INVESTIGATE/PRIORITY maps onto probability bands; **not claimed epidemiologically optimal**.

## Validation

Rolling-origin evaluation; ablation across source families; lead time vs official notification; CRPS / coverage / Brier / ECE.

## Explicit non-choices

- No LSTM/Transformer as default (prompt §35).  
- No claiming “hidden outbreak confirmed”.  
- No LLM-authored probabilities.
