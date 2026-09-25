"""Turn the downloaded Parquet history into training windows (LEHAR Phase 2.5).

Input:  data/flood_history/<district_code>.parquet, written by
        scripts/data/fetch_flood_history.py (REAL GloFAS + ERA5 data).
Output: a FloodWindowDataset — one big normalised feature matrix, a target
        matrix, and three index arrays naming the valid window starts in the
        train / validation / test periods.

Two design decisions worth stating outright, because both are about not
lying to the model:

**Windows never span a gap.** A window is valid only if all
WINDOW_DAYS + max(HORIZONS) days of it are consecutive calendar days with no
missing value in any physical channel. Stitching across a hole would teach
the model that a river jumped when in fact the record simply stopped.

**The split is by TIME, not at random.** Train is everything up to and
including 2022, validation is 2023, test is 2024 onwards, keyed on the issue
day D0 (the last day of the input window). A random split would let the
model see Tuesday and Thursday while being scored on Wednesday — with a
series this autocorrelated that scores near-perfectly and means nothing.
Per-district normalisation statistics are computed on the TRAIN rows only,
for the same reason.

numpy/pandas only — no torch. train.py wraps these arrays in tensors.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ml.districts import DISTRICTS, district_code
from ml.flood_dl.features import (
    FEATURE_NAMES,
    HORIZONS,
    N_FEATURES,
    NORMALISED_CHANNELS,
    WINDOW_DAYS,
    apply_normalisation,
    build_raw_features,
    normalisation_stats,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_HISTORY_DIR = PROJECT_ROOT / "data" / "flood_history"

# Split boundaries, on the issue day D0. Inclusive of the named years.
TRAIN_END_YEAR = 2022
VAL_YEAR = 2023
TEST_START_YEAR = 2024

MAX_HORIZON = max(HORIZONS)
# Days a single usable sample occupies: the input window plus the furthest
# target day.
SPAN_DAYS = WINDOW_DAYS + MAX_HORIZON

REQUIRED_COLUMNS = ("date", "river_discharge_m3s", "precipitation_mm", "temperature_max_c")

SPLIT_TRAIN = "train"
SPLIT_VAL = "val"
SPLIT_TEST = "test"
SPLITS = (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST)


@dataclass
class DistrictSeries:
    """One district's contiguous daily record, as loaded from Parquet."""

    name: str
    code: str
    index: int
    dates: np.ndarray  # datetime64[D]
    raw_features: np.ndarray  # (T, 5), unnormalised
    discharge_m3s: np.ndarray  # (T,) raw m3/s, kept for evaluation
    precipitation_mm: np.ndarray  # (T,) kept for the level-hit-rate evaluation


@dataclass
class FloodWindowDataset:
    """Every district's windows, flattened into one set of arrays.

    A sample is identified by a single integer `start`: its input window is
    rows [start, start + WINDOW_DAYS), its issue day is row
    start + WINDOW_DAYS - 1, and its targets are rows
    start + WINDOW_DAYS + h - 1 for h in HORIZONS. Districts are laid end to
    end in one matrix, and a start index is only ever emitted when the whole
    span stays inside one district (see _valid_starts), so the flattening is
    invisible to the model.
    """

    features: np.ndarray  # (T_total, 5) NORMALISED
    discharge_m3s: np.ndarray  # (T_total,) raw, for evaluation
    precipitation_mm: np.ndarray  # (T_total,) raw, for evaluation
    dates: np.ndarray  # (T_total,) datetime64[D]
    district_ids: np.ndarray  # (T_total,) int64 index into `districts`
    starts: dict[str, np.ndarray]  # split -> int64 array of window starts
    districts: list[str]  # index -> district name, the model's embedding order
    norm: dict[str, dict]  # district name -> {"mean": [...], "std": [...]}
    feature_names: tuple = field(default=FEATURE_NAMES)
    window_days: int = WINDOW_DAYS
    horizons: tuple = field(default=HORIZONS)

    def batch(self, starts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(windows, district_ids, targets) for a batch of start indices.

        Fancy-indexes the shared matrix rather than materialising 1.1 million
        14-day windows up front: the full expansion would be ~325 MB of
        mostly-duplicated float32, and it buys nothing.
        """
        starts = np.asarray(starts, dtype=np.int64)
        offsets = np.arange(WINDOW_DAYS, dtype=np.int64)
        window_rows = starts[:, None] + offsets[None, :]
        windows = self.features[window_rows]  # (B, WINDOW_DAYS, 5)

        target_rows = starts[:, None] + (WINDOW_DAYS + np.asarray(HORIZONS, dtype=np.int64) - 1)[None, :]
        targets = self.features[target_rows, 0]  # normalised log discharge

        issue_rows = starts + WINDOW_DAYS - 1
        return windows, self.district_ids[issue_rows], targets

    def issue_rows(self, starts: np.ndarray) -> np.ndarray:
        """Row index of D0 (the issue day) for each window start."""
        return np.asarray(starts, dtype=np.int64) + WINDOW_DAYS - 1

    def target_rows(self, starts: np.ndarray) -> np.ndarray:
        """(B, len(HORIZONS)) row indices of the target days D0+1..D0+3."""
        starts = np.asarray(starts, dtype=np.int64)
        return starts[:, None] + (WINDOW_DAYS + np.asarray(HORIZONS, dtype=np.int64) - 1)[None, :]

    def summary(self) -> dict:
        return {
            "districts": len(self.districts),
            "total_days": int(len(self.features)),
            "window_days": WINDOW_DAYS,
            "horizons": list(HORIZONS),
            "feature_names": list(FEATURE_NAMES),
            "samples": {split: int(len(self.starts[split])) for split in SPLITS},
            "date_range": {
                "first": str(self.dates.min()),
                "last": str(self.dates.max()),
            },
            "split_boundaries": {
                "train": f"issue day <= {TRAIN_END_YEAR}-12-31",
                "val": f"issue day in {VAL_YEAR}",
                "test": f"issue day >= {TEST_START_YEAR}-01-01",
            },
        }


def load_district_series(code: str, name: str, index: int, history_dir: Path) -> DistrictSeries | None:
    """Read one district's Parquet file, or None if it is missing/unusable."""
    path = history_dir / f"{code}.parquet"
    if not path.exists():
        return None

    frame = pd.read_parquet(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing column(s): {missing}")

    frame = frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if frame.empty:
        return None

    dates = frame["date"].to_numpy(dtype="datetime64[D]")
    discharge = frame["river_discharge_m3s"].to_numpy(dtype=np.float64)
    precipitation = frame["precipitation_mm"].to_numpy(dtype=np.float64)
    temperature = frame["temperature_max_c"].to_numpy(dtype=np.float64)
    day_of_year = pd.DatetimeIndex(frame["date"]).dayofyear.to_numpy()

    raw = build_raw_features(discharge, precipitation, temperature, day_of_year)
    return DistrictSeries(
        name=name,
        code=code,
        index=index,
        dates=dates,
        raw_features=raw,
        discharge_m3s=discharge,
        precipitation_mm=precipitation,
    )


def _valid_starts(series: DistrictSeries) -> np.ndarray:
    """Window starts (local to this district) whose whole SPAN_DAYS span is
    consecutive days with no missing physical value.

    Both conditions are checked with a rolling sum over a boolean array, so
    this stays vectorised over ~11,000 days per district rather than looping.
    """
    length = len(series.dates)
    if length < SPAN_DAYS:
        return np.zeros(0, dtype=np.int64)

    # A day is usable if none of the three physical channels is NaN.
    usable = np.isfinite(series.raw_features[:, :NORMALISED_CHANNELS]).all(axis=1)
    # Day i continues day i-1 if it is exactly one calendar day later. Day 0
    # starts the record and has nothing to continue.
    step_ok = np.empty(length, dtype=bool)
    step_ok[0] = False
    step_ok[1:] = (series.dates[1:] - series.dates[:-1]) == np.timedelta64(1, "D")

    # Every day of the span after its first must be usable AND continue the
    # previous day; the first day only has to be usable, since it is the one
    # starting the run.
    inner_ok = usable & step_ok
    cumulative = np.concatenate([[0], np.cumsum(inner_ok.astype(np.int64))])

    starts = np.arange(length - SPAN_DAYS + 1, dtype=np.int64)
    inner_count = cumulative[starts + SPAN_DAYS] - cumulative[starts + 1]
    return starts[usable[starts] & (inner_count == SPAN_DAYS - 1)]


def _split_for(issue_dates: np.ndarray) -> np.ndarray:
    """Split label per issue day, as an array of SPLITS indices."""
    years = issue_dates.astype("datetime64[Y]").astype(int) + 1970
    labels = np.full(len(years), -1, dtype=np.int64)
    labels[years <= TRAIN_END_YEAR] = 0
    labels[years == VAL_YEAR] = 1
    labels[years >= TEST_START_YEAR] = 2
    return labels


def build_dataset(history_dir: Path | str = DEFAULT_HISTORY_DIR, districts: dict | None = None) -> FloodWindowDataset:
    """Assemble every district's windows into one dataset.

    Districts with no Parquet file, or with too short a record to yield a
    single window, are skipped with their names recorded in `districts` order
    — the embedding table is sized to the districts that actually made it in,
    so a district the model never saw cannot be silently given some other
    district's embedding row at inference time.
    """
    history_dir = Path(history_dir)
    catalogue = districts if districts is not None else DISTRICTS

    kept: list[DistrictSeries] = []
    for name in catalogue:
        series = load_district_series(district_code(name), name, len(kept), history_dir)
        if series is None or len(series.dates) < SPAN_DAYS:
            continue
        series.index = len(kept)
        kept.append(series)

    if not kept:
        raise FileNotFoundError(
            f"No usable district history found in {history_dir}. "
            "Run scripts/data/fetch_flood_history.py first."
        )

    feature_blocks: list[np.ndarray] = []
    starts_by_split: dict[str, list[np.ndarray]] = {split: [] for split in SPLITS}
    norm: dict[str, dict] = {}
    offset = 0

    for series in kept:
        local_starts = _valid_starts(series)
        issue_dates = series.dates[local_starts + WINDOW_DAYS - 1] if len(local_starts) else series.dates[:0]
        labels = _split_for(issue_dates)

        # Train-only statistics: validation and test days must not influence
        # the scale the model is trained in (that is leakage, and it flatters
        # every number in metrics.json).
        train_local = local_starts[labels == 0]
        if len(train_local):
            train_rows = np.unique(
                (train_local[:, None] + np.arange(SPAN_DAYS, dtype=np.int64)[None, :]).ravel()
            )
            stats = normalisation_stats(series.raw_features[train_rows])
        else:
            # No training window at all (a very short record): fall back to
            # the district's whole series rather than dropping it, and say so.
            stats = normalisation_stats(series.raw_features)
        norm[series.name] = stats

        feature_blocks.append(apply_normalisation(series.raw_features, stats))
        for split_index, split in enumerate(SPLITS):
            starts_by_split[split].append(local_starts[labels == split_index] + offset)
        offset += len(series.dates)

    features = np.concatenate(feature_blocks).astype(np.float32)
    dataset = FloodWindowDataset(
        features=features,
        discharge_m3s=np.concatenate([s.discharge_m3s for s in kept]),
        precipitation_mm=np.concatenate([s.precipitation_mm for s in kept]),
        dates=np.concatenate([s.dates for s in kept]),
        district_ids=np.concatenate(
            [np.full(len(s.dates), s.index, dtype=np.int64) for s in kept]
        ),
        starts={split: np.sort(np.concatenate(blocks)).astype(np.int64) for split, blocks in starts_by_split.items()},
        districts=[s.name for s in kept],
        norm=norm,
    )
    assert dataset.features.shape[1] == N_FEATURES
    return dataset


def write_norm_json(dataset: FloodWindowDataset, path: Path) -> dict:
    """The normalisation sidecar the API needs to use an exported model.

    Everything required to reproduce the model's input space lives here, in
    plain JSON: the district order (which IS the embedding table's row
    order), each district's mean/std, and the window/horizon/channel
    contract. app/services/flood_forecast.py refuses to serve a model whose
    norm.json disagrees with ml/flood_dl/features.py."""
    payload = {
        "window_days": WINDOW_DAYS,
        "horizons": list(HORIZONS),
        "feature_names": list(FEATURE_NAMES),
        "normalised_channels": NORMALISED_CHANNELS,
        "districts": list(dataset.districts),
        "per_district": {name: dataset.norm[name] for name in dataset.districts},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
