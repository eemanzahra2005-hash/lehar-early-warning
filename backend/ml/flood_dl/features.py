"""The feature contract shared by training and serving (LEHAR Phase 2.5).

This module is the single source of truth for what the flood lead-time model
eats: how many days of history, which channels, in which order, and how they
are normalised. It is imported by BOTH ml/flood_dl/dataset.py (training) and
app/services/flood_forecast.py (serving), so the two can never drift apart —
a model trained on one feature order and served on another would produce
confident nonsense rather than an error.

numpy only. No torch, no pandas, no I/O — so the API pays a few kilobytes to
import it and nothing more.

The window
----------
14 days of daily history, ending on the day the forecast is issued ("D0"),
predicting log discharge at D0+1, D0+2 and D0+3. Fourteen days is two weeks
of recession/rise behaviour — long enough for the GRU to see a flood wave
building, short enough that a district with a patchy GloFAS record still
yields plenty of usable windows.

The channels
------------
0. log_discharge       log1p(river discharge in m3/s)
1. precipitation_mm    daily precipitation sum
2. temperature_max_c   daily maximum 2 m temperature
3. day_of_year_sin     seasonality, as a continuous circular pair so that
4. day_of_year_cos     31 December and 1 January are adjacent rather than
                       357 days apart

Why log discharge: Pakistan's district reaches span roughly four orders of
magnitude (a Karakoram torrent vs. a desert wadi that is dry most of the
year — see the caveat in docs/FLOOD_DL.md about city-centre coordinates).
Trained on raw m3/s, one Indus district would dominate the loss and the
model would learn nothing about the other 106. log1p also handles the exact
zeros a dry riverbed produces, which plain log does not.

Normalisation is PER DISTRICT (mean/std of each of channels 0-2, computed on
the TRAINING period only — never on validation or test, which would leak).
The two seasonality channels are already bounded in [-1, 1] and are left
alone.
"""

import numpy as np

# Days of history the model reads, ending on the issue day D0 (inclusive).
WINDOW_DAYS = 14

# Lead times, in days ahead of D0, that the model predicts.
HORIZONS = (1, 2, 3)

# Channel order. Changing this order invalidates every exported model, which
# is why norm.json records it and app/services/flood_forecast.py checks it.
FEATURE_NAMES = (
    "log_discharge",
    "precipitation_mm",
    "temperature_max_c",
    "day_of_year_sin",
    "day_of_year_cos",
)
N_FEATURES = len(FEATURE_NAMES)

# The channels per-district normalisation applies to: the three physical
# measurements. The trailing seasonality pair is already in [-1, 1].
NORMALISED_CHANNELS = 3

# Guards a constant series (a desert reach that reads 0.00 m3/s every day)
# from dividing by a zero standard deviation.
MIN_STD = 1e-6

# The mean solar year, so the seasonal cycle does not drift across the
# 29 years of history the model is trained on.
DAYS_PER_YEAR = 365.25


def log_discharge(values: np.ndarray) -> np.ndarray:
    """m3/s -> log1p space. Negative values (never seen from GloFAS, but a
    NaN-fill or a future provider could produce one) are clamped to 0 rather
    than producing a silent NaN."""
    return np.log1p(np.maximum(np.asarray(values, dtype=np.float64), 0.0))


def inverse_log_discharge(values: np.ndarray) -> np.ndarray:
    """log1p space -> m3/s, clamped at 0: a river cannot flow backwards, and
    a slightly-negative prediction near a dry reach is a rounding artefact,
    not a forecast."""
    return np.maximum(np.expm1(np.asarray(values, dtype=np.float64)), 0.0)


def day_of_year_sincos(day_of_year: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Circular seasonality for an array of 1-366 day-of-year numbers."""
    angle = 2.0 * np.pi * (np.asarray(day_of_year, dtype=np.float64) - 1.0) / DAYS_PER_YEAR
    return np.sin(angle), np.cos(angle)


def build_raw_features(
    discharge_m3s: np.ndarray,
    precipitation_mm: np.ndarray,
    temperature_max_c: np.ndarray,
    day_of_year: np.ndarray,
) -> np.ndarray:
    """Stack one district's daily series into an (T, 5) UNNORMALISED matrix
    in FEATURE_NAMES order. All four inputs must be the same length and
    already sorted by date."""
    arrays = (discharge_m3s, precipitation_mm, temperature_max_c, day_of_year)
    lengths = {len(np.asarray(a)) for a in arrays}
    if len(lengths) != 1:
        raise ValueError(f"all series must be the same length, got {sorted(lengths)}")

    sin, cos = day_of_year_sincos(day_of_year)
    return np.column_stack(
        [
            log_discharge(discharge_m3s),
            np.asarray(precipitation_mm, dtype=np.float64),
            np.asarray(temperature_max_c, dtype=np.float64),
            sin,
            cos,
        ]
    )


def normalisation_stats(raw_features: np.ndarray) -> dict:
    """Per-district mean/std of the three physical channels.

    NaNs are ignored rather than propagated: a district with a mid-series gap
    still gets usable statistics from the days it does have. (The windows
    spanning that gap are dropped separately — see dataset.py.)"""
    matrix = np.asarray(raw_features, dtype=np.float64)[:, :NORMALISED_CHANNELS]
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(matrix, axis=0)
        std = np.nanstd(matrix, axis=0)
    # An all-NaN channel yields NaN here; treat it as "no information" (mean
    # 0, unit scale) so it contributes nothing instead of poisoning the row.
    mean = np.nan_to_num(mean, nan=0.0)
    std = np.nan_to_num(std, nan=1.0)
    return {
        "mean": [float(v) for v in mean],
        "std": [float(max(v, MIN_STD)) for v in std],
    }


def apply_normalisation(raw_features: np.ndarray, stats: dict) -> np.ndarray:
    """Normalise channels 0-2 in place of a copy; leave the seasonality pair
    untouched. Works on a single (T, 5) series or a batched (B, T, 5) stack."""
    out = np.array(raw_features, dtype=np.float64, copy=True)
    mean = np.asarray(stats["mean"], dtype=np.float64)
    std = np.asarray(stats["std"], dtype=np.float64)
    out[..., :NORMALISED_CHANNELS] = (out[..., :NORMALISED_CHANNELS] - mean) / std
    return out


def denormalise_discharge(normalised: np.ndarray, stats: dict) -> np.ndarray:
    """Model output (normalised log discharge) -> log discharge. The model
    predicts channel 0's normalised space, so it is channel 0's statistics
    that invert it."""
    mean = float(stats["mean"][0])
    std = float(stats["std"][0])
    return np.asarray(normalised, dtype=np.float64) * std + mean


def predictions_to_m3s(normalised: np.ndarray, stats: dict) -> np.ndarray:
    """The whole inverse chain in one call: what the ONNX graph emits, in
    m3/s. Used by app/services/flood_forecast.py and by train.py's metrics,
    so the offline numbers and the served numbers come out of one function."""
    return inverse_log_discharge(denormalise_discharge(normalised, stats))
