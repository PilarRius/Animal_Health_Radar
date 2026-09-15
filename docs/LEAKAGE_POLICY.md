# Leakage Policy

## Rule

For any prediction stamped with as-of date \(T\), only records with  
`available_from ≤ T` may enter features, parameters, or explanations.

This applies to WAHIS, news, BEACON, PADI, environmental releases, trade, derived features, and model refits.

## Event time vs observation time

| Concept | Typical fields | Role |
|---------|----------------|------|
| Event time | onset, suspicion | Disease process timing |
| Observation time | notification, publication, retrieved_at | Observation process |
| Knowability | `available_from` | Hard filter for as-of |

Using publication date as onset, or confirmation as onset, is forbidden.

## Safeguards

1. **Single choke point:** `src/utils/asof.filter_as_of` (+ reference implementation for tests).
2. **Feature store availability lags** in `config.yaml` (`features.availability_lag_days`).
3. **Temporal train/calibration/test splits** — never random row splits.
4. **Ground-truth latent file** (`_ground_truth_latent_weekly.csv`) readable only by evaluation; leakage tests assert feature builders never open it.
5. **Right-truncated delay likelihood** — fitting delays without truncation would leak completeness of recent weeks into nowcasts.

## Automated tests (required)

Under `tests/leakage/`:

- `test_no_future_events`
- `test_no_future_publications`
- `test_no_future_features`
- `test_as_of_filter`
- `test_train_validation_temporal_separation`
- `test_event_target_leakage`

Failure mode: tests must **fail loudly** if future information enters a historical prediction.

## Environmental latency

ERA5 near-real-time is treated with a configured lag (~6 days). Retrospective reanalysis updates that revise past meteorology are not silently treated as available on the event day.
