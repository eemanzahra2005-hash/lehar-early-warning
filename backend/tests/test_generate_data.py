"""Tests for backend/ml/generate_data.py (synthetic dataset generator).

Uses a small `rows_per_district` sample everywhere for speed — the logic
under test doesn't depend on dataset size.
"""

import pandas as pd

from ml.districts import DISTRICTS
from ml.generate_data import generate_dataset

SAMPLE_ROWS_PER_DISTRICT = 20


def test_generate_dataset_includes_all_districts():
    """Doesn't hardcode the district count — asserts against the live
    DISTRICTS dict so this test stays correct as districts.py grows
    (see PROGRESS.md Phase 5.5, which took the count from 45 to 107)."""
    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)

    assert set(df["district"].unique()) == set(DISTRICTS.keys())
    assert len(df) == len(DISTRICTS) * SAMPLE_ROWS_PER_DISTRICT


def test_generate_dataset_is_deterministic_for_same_seed():
    df1 = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT, seed=42)
    df2 = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT, seed=42)

    pd.testing.assert_frame_equal(df1, df2)


def test_target_has_no_nan_and_stays_within_bounds():
    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)
    target = df["irrigation_recommendation_mm"]

    assert target.isna().sum() == 0
    assert target.min() >= 0
    assert target.max() <= 60
