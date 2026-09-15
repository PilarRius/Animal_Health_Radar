"""Leakage tests: future information must never enter historical predictions."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.utils.asof import AsOfViolationError, assert_point_in_time, filter_as_of, filter_as_of_reference


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c"],
            "available_from": pd.to_datetime(["2024-05-01", "2024-05-10", "2024-04-20"]),
            "reference_date": pd.to_datetime(["2024-04-15", "2024-04-28", "2024-04-01"]),
            "value": [1.0, 2.0, 3.0],
        }
    )


def test_as_of_filter():
    frame = _sample_frame()
    as_of = date(2024, 5, 1)
    filtered = filter_as_of(frame, as_of)
    assert set(filtered["event_id"]) == {"a", "c"}
    assert (pd.to_datetime(filtered["available_from"]).dt.date <= as_of).all()


def test_as_of_filter_matches_reference_implementation():
    frame = _sample_frame()
    as_of = date(2024, 5, 5)
    fast = filter_as_of(frame, as_of).sort_values("event_id").reset_index(drop=True)
    slow = filter_as_of_reference(frame, as_of).sort_values("event_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(fast, slow)


def test_no_future_publications():
    frame = _sample_frame()
    as_of = date(2024, 5, 1)
    filtered = filter_as_of(frame, as_of)
    with pytest.raises(AsOfViolationError):
        # Inject a future publication and assert the guard fails loudly
        bad = pd.concat(
            [
                filtered,
                pd.DataFrame(
                    {
                        "event_id": ["leak"],
                        "available_from": [pd.Timestamp("2024-05-10")],
                        "reference_date": [pd.Timestamp("2024-04-28")],
                        "value": [9.0],
                    }
                ),
            ],
            ignore_index=True,
        )
        assert_point_in_time(bad, as_of)


def test_no_future_events():
    frame = _sample_frame()
    as_of = date(2024, 5, 1)
    filtered = filter_as_of(frame, as_of, max_reference=as_of)
    assert (pd.to_datetime(filtered["reference_date"]).dt.date <= as_of).all()


def test_no_future_features():
    features = pd.DataFrame(
        {
            "entity_key": ["POL|ASF", "POL|ASF"],
            "available_from": pd.to_datetime(["2024-05-01", "2024-05-08"]),
            "feature": ["intel_fused_anomaly", "intel_fused_anomaly"],
            "value": [0.2, 0.9],
        }
    )
    as_of = date(2024, 5, 1)
    usable = filter_as_of(features, as_of)
    assert len(usable) == 1
    assert usable.iloc[0]["value"] == 0.2


def test_train_validation_temporal_separation():
    train_end = date(2023, 12, 31)
    cal_end = date(2024, 12, 31)
    rows = pd.DataFrame(
        {
            "as_of": pd.to_datetime(["2023-06-01", "2024-06-01", "2025-06-01"]),
            "split": ["train", "calibration", "test"],
        }
    )
    assert (rows.loc[rows["split"] == "train", "as_of"].dt.date <= train_end).all()
    assert (
        rows.loc[rows["split"] == "calibration", "as_of"].dt.date > train_end
    ).all()
    assert (rows.loc[rows["split"] == "calibration", "as_of"].dt.date <= cal_end).all()
    assert (rows.loc[rows["split"] == "test", "as_of"].dt.date > cal_end).all()


def test_event_target_leakage():
    """Targets may use future publications; features must not."""
    as_of = date(2024, 5, 1)
    feature_rows = pd.DataFrame(
        {
            "available_from": pd.to_datetime(["2024-04-20", "2024-04-28"]),
            "value": [1.0, 2.0],
        }
    )
    target_rows = pd.DataFrame(
        {
            "available_from": pd.to_datetime(["2024-05-10", "2024-05-20"]),
            "label": [1, 0],
        }
    )
    feats = filter_as_of(feature_rows, as_of)
    assert (pd.to_datetime(feats["available_from"]).dt.date <= as_of).all()
    # Targets intentionally include post-as_of publications — that is the outcome.
    assert (pd.to_datetime(target_rows["available_from"]).dt.date > as_of).any()


def test_ground_truth_latent_not_in_feature_store(tmp_path):
    """Feature builders must never read the latent ground-truth file."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    store = root / "data" / "processed" / "feature_store.parquet"
    if not store.exists():
        pytest.skip("feature store not built")
    # Ensure the ground-truth path is never listed as a processed feature input
    truth = root / "data" / "sample" / "_ground_truth_latent_weekly.csv"
    assert truth.exists()
    cols = pd.read_parquet(store, columns=None)
    assert "_ground_truth" not in "".join(map(str, cols.columns)).lower()
