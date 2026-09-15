# Methodology (summary)

See also `docs/INITIAL_MODEL_DESIGN.md` and `docs/DECISIONS.md`.

## Reporting delay

Right-truncated parametric delay (log-normal / NegBin) with partial pooling by disease × surveillance capacity. Avoids optimistic short-delay bias.

## Latent nowcast

Negative-binomial completion of the right-truncated reporting triangle, divided by an explicit ascertainment prior, optionally smoothed with a local-level state-space model.

## Early warning

Calibrated gradient boosting (or logistic) on point-in-time features. Target = emergence or escalation of **official visibility** within 28 days. Temporal train / calibration / test splits. Explanations via SHAP or occlusion; family counterfactuals by re-scoring with training medians.

## Forecast

CRPS-weighted ensemble of NegBin GLM, damped trend, and seasonal climatology at 7/14/28 days. Predictive mixture distribution.

## Safeguards

As-of filtering (`available_from ≤ T`), independence clusters, no random splits, leakage tests under `tests/leakage/`.
