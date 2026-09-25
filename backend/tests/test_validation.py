"""Tests for backend/ml/validation.py (Phase 8): the pandera schema +
validation report used by ml/pipeline.py's validate() stage. Exercises the
schema directly (not through the pipeline) so failures are attributable to
the schema itself, plus one true end-to-end check against the real
generated dataset CSV on disk."""

import numpy as np
import pandas as pd
import pytest

from ml.generate_data import generate_dataset
from ml.train_model import load_dataset, resolve_data_path
from ml.validation import DataValidationError, validate_training_data


def test_passes_on_a_real_generated_sample():
    df = generate_dataset(rows_per_district=5)
    report = validate_training_data(df)
    assert report.passed is True
    assert report.errors == []
    assert report.missing_values == {}
    assert report.unexpected_categories == {}


def test_passes_on_the_real_dataset_csv_on_disk():
    """The actual training dataset this project ships with must always
    validate cleanly — a real end-to-end check, not just a small sample."""
    df = load_dataset(resolve_data_path())
    report = validate_training_data(df)
    assert report.passed is True
    assert report.errors == []


def test_rejects_out_of_range_temperature():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "temperature_c"] = 80.0
    report = validate_training_data(df)
    assert report.passed is False
    assert any("temperature_c" in e for e in report.errors)


def test_rejects_unknown_crop_type():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "crop_type"] = "banana"
    report = validate_training_data(df)
    assert report.passed is False
    assert any("crop_type" in e for e in report.errors)
    assert report.unexpected_categories.get("crop_type") == ["banana"]


def test_rejects_unknown_district():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "district"] = "Atlantis"
    report = validate_training_data(df)
    assert report.passed is False
    assert any("district" in e for e in report.errors)
    assert report.unexpected_categories.get("district") == ["Atlantis"]


def test_missing_values_report_counts_nulls():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "soil_moisture_pct"] = np.nan
    df.loc[1, "soil_moisture_pct"] = np.nan
    report = validate_training_data(df)
    # soil_moisture_pct is deliberately nullable — nulls alone don't fail validation.
    assert report.passed is True
    assert report.missing_values == {"soil_moisture_pct": 2}


def test_non_nullable_column_with_a_null_fails():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "temperature_c"] = np.nan
    report = validate_training_data(df)
    assert report.passed is False
    assert report.missing_values.get("temperature_c") == 1


def test_unparseable_date_fails():
    df = generate_dataset(rows_per_district=5)
    df["date"] = df["date"].astype(object)
    df.loc[0, "date"] = "not-a-date"
    report = validate_training_data(df)
    assert report.passed is False
    assert any("date" in e for e in report.errors)


def test_missing_required_column_reports_before_schema_check():
    df = generate_dataset(rows_per_district=5).drop(columns=["rainfall_mm"])
    report = validate_training_data(df)
    assert report.passed is False
    assert any("rainfall_mm" in e for e in report.errors)


def test_data_validation_error_message_is_readable():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "district"] = "Atlantis"
    report = validate_training_data(df)
    with pytest.raises(DataValidationError, match="district"):
        raise DataValidationError(report)
