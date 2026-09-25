"""
Synthetic dataset generator for the Smart Irrigation platform.

Generates a SYNTHETIC daily, district-level dataset for Pakistan (107
districts, see districts.py) covering weather, water-supply, and soil-sensor
readings, plus a derived `irrigation_recommendation_mm` target used to train
the baseline RandomForest model in train_model.py.

This is NOT real weather/agriculture data. Every value comes from plausible
but invented formulas, seeded for reproducibility (default seed=42). Any UI
or report that shows this data must label it as synthetic research data.

Run directly to (re)generate the dataset:
    python backend/ml/generate_data.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make `ml` importable as a package whether this file is run directly
# (`python backend/ml/generate_data.py`) or imported from tests/other code.
ML_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ML_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# CROPS re-exported (not just used internally) for existing
# `from ml.generate_data import CROPS` call sites.
from ml.districts import DISTRICTS  # noqa: E402
from ml.feature_schema import CROPS  # noqa: E402,F401

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "synthetic_irrigation_dataset_pk107.csv"

# 107 districts * 733 rows ~= 78,431 rows, at least 700/district
DEFAULT_ROWS_PER_DISTRICT = 733
DEFAULT_START_DATE = "2022-01-01"
DEFAULT_SEED = 42
# Roughly reflects relative cropped-area shares in Pakistan (wheat is grown
# most widely across all provinces; the other four are more regional).
CROP_PROBABILITIES = [0.35, 0.15, 0.15, 0.15, 0.20]

FAULT_TYPES = ["none", "missing_sensor", "stuck_sensor", "time_skew"]
FAULT_PROBABILITIES = [0.94, 0.02, 0.02, 0.02]


def _generate_district_frame(
    name: str, params: dict, dates: pd.DatetimeIndex, rng: np.random.Generator
) -> pd.DataFrame:
    """Build the synthetic daily rows for a single district."""
    n = len(dates)
    day_of_year = dates.dayofyear.to_numpy(dtype=float)
    month = dates.month.to_numpy()
    is_monsoon_month = np.isin(month, [7, 8, 9])

    crop_type = rng.choice(CROPS, size=n, p=CROP_PROBABILITIES)

    # Seasonal sine/cosine curve peaking around day 172 (~June 21, the hot
    # pre-monsoon peak) and troughing in late December, shifted per-district.
    temperature_c = (
        25.0
        + 12.0 * np.cos(2 * np.pi * (day_of_year - 172) / 365.25)
        + params["temp_offset_c"]
        + rng.normal(0, 1.5, size=n)
    )

    monsoon_strength = params["monsoon_strength"]
    humidity_pct = np.clip(
        55.0
        + 10.0 * np.sin(2 * np.pi * (day_of_year - 200) / 365.25)
        + params["humidity_offset"]
        + np.where(is_monsoon_month, 15.0 * monsoon_strength, 0.0)
        + rng.normal(0, 4.0, size=n),
        10.0,
        95.0,
    )

    # Exponential rainfall: mostly light/no rain, occasional heavy days.
    # The monsoon (Jul-Sep) raises the expected value, scaled per-district.
    rain_scale = np.where(is_monsoon_month, 2.0 + 18.0 * monsoon_strength, 1.5)
    rainfall_mm = rng.exponential(rain_scale, size=n)

    # Simplified ET0 proxy: rises with temperature, falls with humidity.
    evapotranspiration_mm = np.clip(
        2.0 + 0.15 * temperature_c - 0.05 * humidity_pct + rng.normal(0, 0.5, size=n),
        0.2,
        12.0,
    )

    # Canal discharge oscillates around the district baseline: higher in the
    # Kharif season (summer, snowmelt + monsoon), lower in Rabi/winter.
    seasonal_canal_factor = 1.0 + 0.3 * np.sin(2 * np.pi * (day_of_year - 172) / 365.25)
    baseline = params["canal_flow_baseline_cusecs"]
    canal_flow_cusecs = np.clip(
        baseline * seasonal_canal_factor + rng.normal(0, baseline * 0.05, size=n),
        0,
        None,
    )

    soil_moisture_pct = np.clip(
        20.0
        + 0.15 * rainfall_mm
        + 0.02 * canal_flow_cusecs
        - 1.1 * evapotranspiration_mm
        + rng.normal(0, 3.0, size=n),
        5.0,
        60.0,
    )

    sensor_fault_type = rng.choice(FAULT_TYPES, size=n, p=FAULT_PROBABILITIES)
    was_imputed = np.zeros(n, dtype=int)

    # Simulate missing/stuck soil-moisture sensors by copying the previous
    # day's reading forward (day 0 of a district has no previous reading, so
    # it is left as the freshly-computed value). time_skew is a timestamp-
    # level fault and intentionally does not alter any sensor value here.
    for i in range(1, n):
        if sensor_fault_type[i] in ("missing_sensor", "stuck_sensor"):
            soil_moisture_pct[i] = soil_moisture_pct[i - 1]
            was_imputed[i] = 1

    # Target: more irrigation needed when soil is dry and ET0 is high, less
    # when it recently rained. Purely a synthetic formula, not agronomic
    # ground truth.
    irrigation_recommendation_mm = np.round(
        np.clip(
            (35.0 - soil_moisture_pct) * 0.9
            + evapotranspiration_mm * 1.3
            - rainfall_mm * 0.4,
            0.0,
            60.0,
        ),
        1,
    )

    return pd.DataFrame(
        {
            "date": dates,
            "district": name,
            "crop_type": crop_type,
            "temperature_c": np.round(temperature_c, 2),
            "humidity_pct": np.round(humidity_pct, 2),
            "rainfall_mm": np.round(rainfall_mm, 2),
            "evapotranspiration_mm": np.round(evapotranspiration_mm, 2),
            "canal_flow_cusecs": np.round(canal_flow_cusecs, 1),
            "soil_moisture_pct": np.round(soil_moisture_pct, 2),
            "sensor_fault_type": sensor_fault_type,
            "was_imputed": was_imputed,
            "month": month,
            "day_of_year": day_of_year.astype(int),
            "irrigation_recommendation_mm": irrigation_recommendation_mm,
        }
    )


def generate_dataset(
    rows_per_district: int = DEFAULT_ROWS_PER_DISTRICT,
    start_date: str = DEFAULT_START_DATE,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Generate the full synthetic dataset (all districts in DISTRICTS).

    A fresh `np.random.default_rng(seed)` is created on every call, so calling
    this twice with the same arguments always returns an identical DataFrame.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start_date, periods=rows_per_district, freq="D")

    frames = [
        _generate_district_frame(name, params, dates, rng)
        for name, params in DISTRICTS.items()
    ]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    df = generate_dataset()

    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(DEFAULT_OUTPUT_PATH, index=False)

    print(f"Wrote {len(df):,} rows ({len(DISTRICTS)} districts) to {DEFAULT_OUTPUT_PATH}")
    print("\nRows per district:")
    print(df["district"].value_counts().sort_index().to_string())
    print("\nOverall numeric stats:")
    print(df.describe(include="number").to_string())
