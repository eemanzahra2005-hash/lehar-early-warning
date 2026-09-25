"""LEHAR Phase 2.5: the pure helpers inside
scripts/data/fetch_flood_history.py.

The script itself is a network tool and is never run by the suite — but three
of its decisions are pure, consequential and worth pinning down offline:

  _trim_leading_gap      where each district's usable record BEGINS. GloFAS
                         coverage does not reach 1984 for every river reach,
                         and getting this wrong would either throw away real
                         data or feed the model a run of nulls.
  _existing_is_current   what makes the script resumable — i.e. whether a
                         rerun re-downloads 107 districts or none.
  _seconds_until_next_hour  the wait that rides out Open-Meteo's hourly
                         fair-use limit instead of burning retries.

Loaded by path, because scripts/ is not an importable package.
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "data" / "fetch_flood_history.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("fetch_flood_history", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load_script()


def _frame(discharge, start="2019-01-01"):
    dates = pd.date_range(start, periods=len(discharge), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "river_discharge_m3s": pd.Series(discharge, dtype="float64"),
            "precipitation_mm": [1.0] * len(discharge),
            "temperature_max_c": [30.0] * len(discharge),
        }
    )


# --- _trim_leading_gap ------------------------------------------------------


def test_leading_nulls_are_dropped_so_each_district_starts_at_its_own_first_reading():
    frame = _frame([None, None, None, 1.5, 2.0, 2.5])
    trimmed = fetch._trim_leading_gap(frame)

    assert len(trimmed) == 3
    assert trimmed["date"].min() == pd.Timestamp("2019-01-04")
    assert trimmed["river_discharge_m3s"].iloc[0] == 1.5


def test_a_record_with_no_leading_gap_is_returned_whole():
    frame = _frame([1.0, 2.0, 3.0])
    assert len(fetch._trim_leading_gap(frame)) == 3


def test_a_district_with_no_discharge_at_all_yields_an_empty_frame():
    """A coordinate GloFAS models no reach for must produce nothing, not a
    column of zeros — the caller reports it as "empty" rather than writing a
    fabricated series (CLAUDE.md rule 4)."""
    frame = _frame([None, None, None])
    assert fetch._trim_leading_gap(frame).empty


def test_gaps_in_the_MIDDLE_of_a_record_are_deliberately_preserved():
    """Only the LEADING run is trimmed. An interior hole has to survive into
    the Parquet file so ml/flood_dl/dataset.py can refuse to build a window
    across it — filling it here would hide the hole from the one component
    whose job is to notice it."""
    frame = _frame([1.0, 2.0, None, 4.0, 5.0])
    trimmed = fetch._trim_leading_gap(frame)

    assert len(trimmed) == 5
    assert trimmed["river_discharge_m3s"].isna().sum() == 1


def test_trimming_resets_the_index_so_the_written_parquet_starts_at_row_zero():
    trimmed = fetch._trim_leading_gap(_frame([None, None, 3.0, 4.0]))
    assert list(trimmed.index) == [0, 1]


# --- _existing_is_current (what makes the script resumable) -----------------


def test_a_missing_file_is_never_current(tmp_path):
    assert fetch._existing_is_current(tmp_path / "nope.parquet", "2026-09-18") is False


def test_a_file_reaching_the_requested_end_date_is_current(tmp_path):
    path = tmp_path / "d.parquet"
    _frame([1.0] * 5, start="2026-09-14").to_parquet(path, index=False)
    assert fetch._existing_is_current(path, "2026-09-18") is True


def test_a_file_that_stops_short_is_refetched(tmp_path):
    path = tmp_path / "d.parquet"
    _frame([1.0] * 3, start="2026-09-14").to_parquet(path, index=False)
    assert fetch._existing_is_current(path, "2026-09-18") is False


def test_an_unreadable_file_is_refetched_rather_than_crashing_the_run(tmp_path):
    path = tmp_path / "d.parquet"
    path.write_bytes(b"this is not parquet")
    assert fetch._existing_is_current(path, "2026-09-18") is False


def test_an_empty_file_is_refetched(tmp_path):
    path = tmp_path / "d.parquet"
    _frame([]).to_parquet(path, index=False)
    assert fetch._existing_is_current(path, "2026-09-18") is False


# --- the hourly-limit wait --------------------------------------------------


def test_the_hourly_wait_lands_just_past_the_next_hour_boundary():
    """Open-Meteo's hourly budget resets on the hour, so the retry has to wait
    for the boundary — plus a grace margin, so a slightly-out-of-step clock
    cannot land it in the last second of the exhausted hour."""
    wait = fetch._seconds_until_next_hour()
    assert 0 < wait <= 3600 + fetch.HOUR_RESET_GRACE_SECONDS

    now = datetime.now(timezone.utc)
    landing = now + timedelta(seconds=wait)
    assert landing > now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def test_the_hourly_limit_marker_matches_what_open_meteo_actually_returns():
    """The real response body, observed during this phase's download:
    {"error":true,"reason":"Hourly API request limit exceeded. Please try
    again in the next hour."} — matched case-insensitively."""
    body = '{"error":true,"reason":"Hourly API request limit exceeded. Please try again in the next hour."}'
    assert fetch.HOURLY_LIMIT_MARKER in body.lower()


# --- the contract with the rest of the pipeline -----------------------------


def test_the_script_writes_exactly_the_columns_the_dataset_builder_requires():
    from ml.flood_dl.dataset import REQUIRED_COLUMNS

    produced = set(_frame([1.0, 2.0]).columns)
    assert set(REQUIRED_COLUMNS) <= produced


def test_attribution_names_both_providers_as_their_licences_require():
    assert "Open-Meteo" in fetch.ATTRIBUTION
    assert "CC BY 4.0" in fetch.ATTRIBUTION
    assert "GloFAS" in fetch.ATTRIBUTION


def test_the_default_start_date_still_asks_for_everything():
    """The shipped dataset starts in 2019 because of API quota, not because
    the script assumes that. Anyone with more quota reruns it unchanged."""
    assert fetch.DEFAULT_START_DATE == "1984-01-01"


@pytest.mark.parametrize("value", [0.0, 12.5, np.nan])
def test_frames_survive_the_float_values_glofas_actually_returns(value):
    frame = _frame([value, 1.0, 2.0])
    assert len(fetch._trim_leading_gap(frame)) in (2, 3)
