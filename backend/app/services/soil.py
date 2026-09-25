"""Live soil moisture helpers (Phase 16).

Pure functions (no I/O) that reduce Open-Meteo's hourly soil-moisture layers
to this project's `soil_moisture_pct` model feature. The network call itself
lives in app/services/weather.py's WeatherService.fetch_soil_moisture(), so it
reuses the exact same timeout, retry, cache, and failure handling as weather.
Full mapping rationale: docs/SOIL_MOISTURE.md.

HONESTY NOTE: Open-Meteo soil moisture is a weather-MODEL ESTIMATE for a grid
cell around the district's main city — not a reading from a sensor in anyone's
field, and it knows nothing about irrigation a farmer has applied. Every
reading built here carries SOURCE_LIVE + LIVE_LABEL so the API, the UI, and
the assistant always say so.
"""

from datetime import datetime

# Open-Meteo hourly variable -> layer thickness (cm): 1-3 cm, 3-9 cm, 9-27 cm.
# Weighting by thickness makes the average proportional to the water actually
# held in each layer — the thin 2 cm surface layer (which dries fastest) must
# not count as much as the 18 cm layer below it.
LAYER_THICKNESS_CM = {
    "soil_moisture_1_to_3cm": 2.0,
    "soil_moisture_3_to_9cm": 6.0,
    "soil_moisture_9_to_27cm": 18.0,
}
SOIL_MOISTURE_VARIABLES = tuple(LAYER_THICKNESS_CM)

# m³/m³ (volumetric water fraction) -> volumetric percent. The model's
# soil_moisture_pct feature is read as volumetric percent (see
# docs/SOIL_MOISTURE.md for the evidence), so this is a pure unit conversion —
# no field-capacity constant is involved.
M3_PER_M3_TO_PCT = 100.0

SOURCE_LIVE = "live (Open-Meteo model estimate)"
SOURCE_MANUAL = "manual"
LIVE_LABEL = "model-estimated — Open-Meteo, not a field sensor"
LAYER_UNIT = "m³/m³"


def depth_weighted_root_zone(layers: dict[str, float]) -> float:
    """Thickness-weighted mean of the three layers, in m³/m³:
    (2*θ[1-3cm] + 6*θ[3-9cm] + 18*θ[9-27cm]) / 26."""
    total_cm = sum(LAYER_THICKNESS_CM.values())
    return sum(layers[name] * cm for name, cm in LAYER_THICKNESS_CM.items()) / total_cm


def to_soil_moisture_pct(volumetric_fraction: float) -> float:
    """m³/m³ -> the model's soil_moisture_pct (volumetric %), rounded to 0.1.
    Clamped to 0-100 — the same bound POST /predict enforces on a manual
    value — so a live value can never be one the API itself would reject."""
    return round(min(100.0, max(0.0, volumetric_fraction * M3_PER_M3_TO_PCT)), 1)


def latest_complete_hour(hourly: dict, now_local: datetime) -> tuple[str, dict[str, float]] | None:
    """The most recent hour at or before `now_local` where all three layers
    have a value. Open-Meteo's hourly arrays also contain the rest of today's
    FORECAST hours, which are skipped — "latest available" means now, not
    later today. Returns None if no hour qualifies."""
    times = hourly["time"]
    series = {name: hourly[name] for name in SOIL_MOISTURE_VARIABLES}
    for i in range(len(times) - 1, -1, -1):
        if datetime.fromisoformat(times[i]) > now_local:
            continue
        values = {name: series[name][i] if i < len(series[name]) else None for name in SOIL_MOISTURE_VARIABLES}
        if all(value is not None for value in values.values()):
            return times[i], {name: float(value) for name, value in values.items()}
    return None


def build_reading(layers: dict[str, float], observed_at: str) -> dict:
    """One live soil-moisture reading: the mapped model-space value plus the
    raw layer values it came from, kept for transparency."""
    root_zone = depth_weighted_root_zone(layers)
    return {
        "soil_moisture_pct": to_soil_moisture_pct(root_zone),
        "source": SOURCE_LIVE,
        "label": LIVE_LABEL,
        "layers": {
            **{name: round(layers[name], 4) for name in SOIL_MOISTURE_VARIABLES},
            "root_zone": round(root_zone, 4),
            "unit": LAYER_UNIT,
            "observed_at": observed_at,
        },
    }
