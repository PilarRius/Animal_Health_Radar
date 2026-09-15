# Target Definition

## Scientific framing

Targets separate **what became officially visible** (scorable) from **latent activity** (estimated under explicit ascertainment assumptions).

## Early-warning target

Configured in `config/config.yaml` → `early_warning`:

**Question:** Given information available at as-of date \(T\), what is  
\(P(\text{officially visible activity appears or materially intensifies within horizon } H \mid \mathcal{F}_T)\)?

Implementation (`label_horizon_days = 28`, `escalation_factor = 1.5`):

- Let \(R_T\) be the current visible run-rate over `run_rate_weeks` (default 8).
- Label = 1 if publications in \((T, T+H]\) ≥ \(\max(1, 1.5 \times R_T \times H/\text{window})\).
- Quiet countries → emergence (any new notification).
- Already-reporting countries → escalation beyond run-rate.

**Why this definition:** Supported by the event structure of the (sample) WAHIS corpus; avoids a pure “any future record” target that is trivial during endemic seasons and avoids requiring unobservable latent labels for supervised EW training.

Temporal split: train ≤ 2023-12-31 · calibration ≤ 2024-12-31 · test after (no shuffle).

## Nowcast target

Estimate latent outbreak count for recent reference weeks given right-truncated official observations and fitted reporting-delay distribution.

- Observable component: outbreaks with `available_from ≤ T`.
- Latent component: delay-adjusted estimate ÷ ascertainment prior (config prior, **not** claimed as estimated from data alone).

## Forecast target

Configured `forecast.target: reported_final`:

- Count of outbreaks with reference week in the horizon that are **eventually** reported (scorable).
- Optionally rescaled to latent scale using the same ascertainment prior (`report_latent_scale: true`), with both scales surfaced separately.

Horizons: 7 / 14 / 28 days.

## Non-targets

- Do not train to predict “next WAHIS row id”.
- Do not treat absence of WAHIS as absence of disease.
- Do not treat SPS / simulation exercises as outbreaks.
