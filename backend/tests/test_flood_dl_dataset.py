"""LEHAR Phase 2.5: the flood lead-time model's feature contract and dataset
builder — ml/flood_dl/features.py and ml/flood_dl/dataset.py, plus the
district-code helpers they depend on.

No torch, no network, no trained model: everything here is numpy/pandas over
Parquet files written into a tmp_path. That is deliberate — these are the
two modules the SERVING path imports, so they must be testable (and
importable) in an environment where PyTorch does not exist at all.
"""

import numpy as np
import pandas as pd
import pytest

from ml.districts import DISTRICTS, district_code, district_codes, district_for_code
from ml.flood_dl.dataset import (
    SPAN_DAYS,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    build_dataset,
    write_norm_json,
)
from ml.flood_dl.features import (
    FEATURE_NAMES,
    HORIZONS,
    MIN_STD,
    N_FEATURES,
    WINDOW_DAYS,
    apply_normalisation,
    build_raw_features,
    denormalise_discharge,
    inverse_log_discharge,
    log_discharge,
    normalisation_stats,
    predictions_to_m3s,
)

THREE_DISTRICTS = list(DISTRICTS)[:3]


# --- district codes ---------------------------------------------------------


def test_every_district_code_is_unique():
    """A collision would silently make two districts share one data file and
    one embedding row — the kind of bug that produces plausible numbers."""
    codes = district_codes()
    assert len(set(codes.values())) == len(DISTRICTS) == 107


def test_district_code_is_filesystem_safe_and_reversible():
    assert district_code("Rahim Yar Khan") == "rahim_yar_khan"
    for name in DISTRICTS:
        code = district_code(name)
        assert code == code.lower()
        assert all(character.isalnum() or character == "_" for character in code)
        assert district_for_code(code) == name


def test_district_for_code_returns_none_for_an_unknown_code():
    assert district_for_code("atlantis") is None


# --- features ---------------------------------------------------------------


def test_log_discharge_round_trips_and_clamps_negatives():
    values = np.array([0.0, 0.5, 12.0, 1000.0])
    assert np.allclose(inverse_log_discharge(log_discharge(values)), values)
    # A negative discharge is not physical; it must become 0, not NaN.
    assert log_discharge(np.array([-5.0]))[0] == 0.0


def test_day_of_year_channels_make_december_and_january_adjacent():
    """The whole reason seasonality is a sin/cos PAIR rather than a number."""
    raw = build_raw_features([1.0, 1.0], [0.0, 0.0], [20.0, 20.0], [365, 1])
    december, january = raw[0, 3:5], raw[1, 3:5]
    # Adjacent on the circle: the two unit vectors are nearly identical.
    assert np.linalg.norm(december - january) < 0.05


def test_build_raw_features_has_the_declared_shape_and_order():
    raw = build_raw_features([4.0, 9.0], [1.0, 2.0], [30.0, 31.0], [10, 11])
    assert raw.shape == (2, N_FEATURES) == (2, len(FEATURE_NAMES))
    assert np.allclose(raw[:, 0], np.log1p([4.0, 9.0]))
    assert np.allclose(raw[:, 1], [1.0, 2.0])
    assert np.allclose(raw[:, 2], [30.0, 31.0])


def test_build_raw_features_rejects_ragged_inputs():
    with pytest.raises(ValueError):
        build_raw_features([1.0, 2.0], [1.0], [30.0, 31.0], [10, 11])


def test_normalisation_leaves_the_seasonality_channels_untouched():
    raw = build_raw_features([1.0, 8.0, 20.0], [0.0, 5.0, 10.0], [25.0, 35.0, 45.0], [1, 100, 200])
    stats = normalisation_stats(raw)
    normalised = apply_normalisation(raw, stats)

    assert np.allclose(normalised[:, 3:5], raw[:, 3:5])
    # The three physical channels come out standardised.
    assert np.allclose(normalised[:, :3].mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(normalised[:, :3].std(axis=0), 1.0, atol=1e-9)


def test_normalisation_survives_a_constant_series():
    """A desert reach reading 0.00 m3/s every day has zero variance — it must
    not divide by zero and produce NaN for the whole district."""
    raw = build_raw_features([0.0] * 5, [0.0] * 5, [30.0] * 5, [1, 2, 3, 4, 5])
    stats = normalisation_stats(raw)
    assert min(stats["std"]) >= MIN_STD
    assert np.isfinite(apply_normalisation(raw, stats)).all()


def test_normalisation_ignores_nan_days():
    raw = build_raw_features([1.0, np.nan, 3.0], [1.0, 2.0, 3.0], [30.0, 31.0, 32.0], [1, 2, 3])
    stats = normalisation_stats(raw)
    assert all(np.isfinite(stats["mean"])) and all(np.isfinite(stats["std"]))


def test_predictions_to_m3s_inverts_the_whole_chain():
    stats = {"mean": [1.5, 0.0, 0.0], "std": [0.4, 1.0, 1.0]}
    discharge = np.array([0.0, 2.5, 140.0])
    normalised = (np.log1p(discharge) - stats["mean"][0]) / stats["std"][0]
    assert np.allclose(predictions_to_m3s(normalised, stats), discharge)
    assert np.allclose(denormalise_discharge(normalised, stats), np.log1p(discharge))


def test_predictions_to_m3s_never_returns_a_negative_river():
    stats = {"mean": [1.5, 0.0, 0.0], "std": [0.4, 1.0, 1.0]}
    assert (predictions_to_m3s(np.array([-99.0, -1.0]), stats) >= 0.0).all()


# --- dataset ----------------------------------------------------------------


def _write_history(directory, name, days=400, start="2021-06-01", gap_at=None, nan_at=None):
    """A synthetic per-district Parquet file shaped exactly like the one
    scripts/data/fetch_flood_history.py writes."""
    dates = pd.date_range(start, periods=days, freq="D")
    frame = pd.DataFrame(
        {
            "date": dates,
            "river_discharge_m3s": np.linspace(1.0, 20.0, days),
            "precipitation_mm": np.tile([0.0, 2.0, 5.0, 1.0], days // 4 + 1)[:days],
            "temperature_max_c": np.linspace(20.0, 40.0, days),
        }
    )
    if nan_at is not None:
        frame.loc[nan_at, "river_discharge_m3s"] = np.nan
    if gap_at is not None:
        frame = frame.drop(index=gap_at).reset_index(drop=True)
    frame.to_parquet(directory / f"{district_code(name)}.parquet", index=False)
    return frame


def test_build_dataset_splits_by_time_and_keeps_the_feature_contract(tmp_path):
    for name in THREE_DISTRICTS:
        _write_history(tmp_path, name, days=1200, start="2021-06-01")

    dataset = build_dataset(tmp_path)

    assert dataset.districts == THREE_DISTRICTS
    assert dataset.features.shape[1] == N_FEATURES
    assert dataset.window_days == WINDOW_DAYS
    assert dataset.horizons == HORIZONS

    # Every split is non-empty and they never overlap.
    all_starts = np.concatenate([dataset.starts[split] for split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST)])
    assert len(set(all_starts.tolist())) == len(all_starts)
    for split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        assert len(dataset.starts[split]) > 0

    # ...and the split really is chronological, on the issue day.
    train_issue = dataset.dates[dataset.issue_rows(dataset.starts[SPLIT_TRAIN])]
    val_issue = dataset.dates[dataset.issue_rows(dataset.starts[SPLIT_VAL])]
    test_issue = dataset.dates[dataset.issue_rows(dataset.starts[SPLIT_TEST])]
    assert train_issue.max() < val_issue.min() <= val_issue.max() < test_issue.min()
    assert str(val_issue.min())[:4] == "2023" and str(val_issue.max())[:4] == "2023"


def test_windows_never_span_a_date_gap(tmp_path):
    """A missing week must not be stitched shut — that would teach the model
    a jump the river never made."""
    name = THREE_DISTRICTS[0]
    _write_history(tmp_path, name, days=400, start="2021-06-01", gap_at=range(200, 207))

    dataset = build_dataset(tmp_path)
    for split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        for start in dataset.starts[split]:
            span = dataset.dates[start : start + SPAN_DAYS]
            steps = np.diff(span).astype("timedelta64[D]").astype(int)
            assert (steps == 1).all(), f"window at {start} spans a gap"


def test_windows_never_span_a_missing_value(tmp_path):
    name = THREE_DISTRICTS[0]
    _write_history(tmp_path, name, days=400, start="2021-06-01", nan_at=250)

    dataset = build_dataset(tmp_path)
    for split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        for start in dataset.starts[split]:
            window = dataset.features[start : start + SPAN_DAYS, :3]
            assert np.isfinite(window).all(), f"window at {start} contains a NaN"
    # The NaN day itself is still present in the underlying series — it is the
    # WINDOWS that avoid it, not the data that was silently filled in.
    assert not np.isfinite(dataset.features[:, 0]).all()


def test_normalisation_statistics_come_from_the_training_period_only(tmp_path):
    """Leakage check: if validation/test days fed the normalisation, every
    metric in metrics.json would be quietly flattered."""
    name = THREE_DISTRICTS[0]
    frame = _write_history(tmp_path, name, days=1600, start="2020-01-01")

    dataset = build_dataset(tmp_path)
    train_only = frame[frame["date"] <= "2022-12-31"]
    expected = normalisation_stats(
        build_raw_features(
            train_only["river_discharge_m3s"],
            train_only["precipitation_mm"],
            train_only["temperature_max_c"],
            pd.DatetimeIndex(train_only["date"]).dayofyear,
        )
    )
    actual = dataset.norm[name]
    # The train rows a window actually touches are a subset of the training
    # period, so the two agree closely without being bit-identical.
    assert actual["mean"][0] == pytest.approx(expected["mean"][0], rel=0.05)
    assert actual["std"][0] == pytest.approx(expected["std"][0], rel=0.05)

    whole_series = normalisation_stats(
        build_raw_features(
            frame["river_discharge_m3s"],
            frame["precipitation_mm"],
            frame["temperature_max_c"],
            pd.DatetimeIndex(frame["date"]).dayofyear,
        )
    )
    assert actual["mean"][0] != pytest.approx(whole_series["mean"][0], rel=1e-6)


def test_batch_returns_aligned_windows_targets_and_district_ids(tmp_path):
    for name in THREE_DISTRICTS:
        _write_history(tmp_path, name, days=900, start="2021-01-01")
    dataset = build_dataset(tmp_path)

    starts = dataset.starts[SPLIT_TRAIN][:16]
    windows, district_ids, targets = dataset.batch(starts)

    assert windows.shape == (len(starts), WINDOW_DAYS, N_FEATURES)
    assert targets.shape == (len(starts), len(HORIZONS))
    assert district_ids.shape == (len(starts),)

    # The target really is the normalised log discharge h days after the
    # window's last day — not off by one.
    for row, start in enumerate(starts):
        assert np.allclose(windows[row], dataset.features[start : start + WINDOW_DAYS])
        for column, horizon in enumerate(HORIZONS):
            assert targets[row, column] == dataset.features[start + WINDOW_DAYS + horizon - 1, 0]


def test_a_window_never_crosses_from_one_district_into_the_next(tmp_path):
    for name in THREE_DISTRICTS:
        _write_history(tmp_path, name, days=500, start="2021-01-01")
    dataset = build_dataset(tmp_path)

    for split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        for start in dataset.starts[split]:
            span_ids = dataset.district_ids[start : start + SPAN_DAYS]
            assert len(set(span_ids.tolist())) == 1, f"window at {start} crosses districts"


def test_districts_without_history_are_skipped_not_invented(tmp_path):
    """The embedding table is sized to the districts that made it in, so a
    district the model never saw can never be given another one's row."""
    _write_history(tmp_path, THREE_DISTRICTS[0], days=500, start="2021-01-01")
    dataset = build_dataset(tmp_path)
    assert dataset.districts == [THREE_DISTRICTS[0]]


def test_build_dataset_raises_when_there_is_no_history_at_all(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_flood_history"):
        build_dataset(tmp_path)


def test_write_norm_json_records_the_whole_serving_contract(tmp_path):
    for name in THREE_DISTRICTS:
        _write_history(tmp_path, name, days=900, start="2021-01-01")
    dataset = build_dataset(tmp_path)

    path = tmp_path / "norm.json"
    payload = write_norm_json(dataset, path)

    assert path.exists()
    assert payload["window_days"] == WINDOW_DAYS
    assert tuple(payload["horizons"]) == HORIZONS
    assert tuple(payload["feature_names"]) == FEATURE_NAMES
    # District ORDER is the embedding row order — it must be recorded, not
    # re-derived at serving time from ml/districts.py.
    assert payload["districts"] == dataset.districts
    for name in dataset.districts:
        assert len(payload["per_district"][name]["mean"]) == 3
        assert len(payload["per_district"][name]["std"]) == 3
