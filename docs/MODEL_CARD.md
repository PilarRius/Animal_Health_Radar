# Model Card — Animal Health Radar (v0.1)

| Field | Value |
|-------|-------|
| Purpose | Early warning, latent nowcast, short-term forecast under delayed surveillance |
| Diseases | HPAI, ASF (config-extensible) |
| Geography | 20-country European / neighbourhood panel (sample) |
| Unit | country × disease × week |
| Training / calibration / test | Temporal splits in `config.yaml` |
| Inputs | Vintage-correct official history, intelligence, environment, livestock exposure, reporting features |
| Outputs | Calibrated EW probability, latent mean ± interval, reporting gap, 7/14/28 forecasts, explanations |
| Assumptions | Ascertainment prior by surveillance tier; synthetic generative process in sample mode |
| Known biases | Reporting intensity ≠ disease risk; media clusters are dependent; synthetic lead is optimistic |
| Failure modes | Thin strata; end-of-corpus labels; treating model estimates as confirmed outbreaks |
| Interpretation | Always label as MODEL ESTIMATE about official visibility / estimated latent activity |
