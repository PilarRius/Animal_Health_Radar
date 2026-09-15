# Leakage Audit

**Audit status:** Policy and as-of primitives implemented; automated leakage suite to be executed after train stage lands.

## Controls inspected

| Control | Location | Status |
|---------|----------|--------|
| As-of filter | `src/utils/asof.py` | Implemented |
| Dual implementation (fast + naive reference) | same | Implemented for test parity |
| Feature availability lags | `config/config.yaml` | Configured |
| Reporting triangle vintage reconstruction | `src/features/temporal.py` | Implemented |
| EMPRES-i downstream flag | ingest + linkage | Implemented |
| Latent ground-truth isolation | `data/sample/README_SAMPLE.md` | Documented |
| Temporal EW split | `early_warning.train_end` / `calibration_end` | Configured |

## Known residual risks

1. **Ascertainment prior** is config-supplied; mis-specifying it biases latent scale but is labelled as prior.
2. **Sample intelligence lead** is generated from latent process — optimistic relative to real media noise; evaluation on synthetic data overstates lead-time gains vs live WAHIS.
3. **When real WAHIS arrives**, field mapping errors could silently use confirmation/publication as onset — require schema regression tests on first real ingest.

## Pass criteria before claiming “no leakage”

All `tests/leakage/` green on a clean `pytest` run after `run_pipeline.py`.
