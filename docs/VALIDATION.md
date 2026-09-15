# Validation

Rolling-origin temporal validation is configured in `config/config.yaml`.

Current synthetic-corpus snapshot (from `scripts/train.py` / `scripts/evaluate.py`):

- Early-warning test PR-AUC ≈ 0.71, ECE ≈ 0.015 (sample mode)
- Forecast ensemble CRPS-weighted: NegBin GLM dominates, then seasonal, then damped trend

Artefacts:

- `reports/validation/metrics.json`
- `data/processed/models/early_warning_metrics.json`
- `data/processed/models/forecast_meta.json`

**Do not claim real-world superiority** until the same protocol is run on the WOAH pilot extract.
