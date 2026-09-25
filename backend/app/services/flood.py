"""Flood Watch: real GloFAS river-discharge data from the free Open-Meteo
Flood API, combined into a transparent, documented Flood Risk Index.

Data source: https://flood-api.open-meteo.com/v1/flood (no API key). Confirmed
by a real test call during Phase 5.5 development — the response shape is:

    {
      "daily_units": {"time": "iso8601", "river_discharge": "m³/s"},
      "daily": {"time": [<ISO date>, ...], "river_discharge": [<float>, ...]}
    }

With `past_days=30&forecast_days=7`, the response is ONE combined 37-entry
series (no separate "past"/"forecast" keys) — the first 30 entries are the
30 days before today, and the last 7 are today plus the next 6 days. This
client slices that combined series itself (see `_split_series`).

Known limitation: district coordinates (ml/districts.py) are each district's
approximate city-center location — the same synthetic placeholders used by
app/services/weather.py — not a point on the riverbank. GloFAS attaches each
query to its nearest modeled river reach, which for districts set back from
the main channel may be a minor local stream rather than the Indus/Chenab/
Kabul mainstem. The discharge numbers returned are real, live GloFAS output
(never fabricated) — but treat them as an approximate, city-level signal, not
a precise gauge reading. See docs/FLOOD_RISK.md for the full methodology and
the mandatory "not an official flood warning" disclaimer.

Rainfall inputs for the risk index come from the existing WeatherService's
16-day forecast (Open-Meteo's main forecast API), not the flood API, which
only returns discharge.
"""

import logging
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from fastapi import HTTPException, status

from app.config import get_settings
from app.metrics import flood_api_failures_total
from app.services.weather import WeatherService
from app.validators import validate_district
from ml.districts import DISTRICTS

logger = logging.getLogger("app.flood")

FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"
MAX_ATTEMPTS = 3  # 1 initial attempt + 2 retries, only on 5xx responses
MAX_CONCURRENT_FLOOD_REQUESTS = 8

PAST_DAYS = 30
FORECAST_DAYS = 7
RAIN_FORECAST_DAYS = 3

# Floor for the discharge baseline so a bone-dry (0 m^3/s) riverbed never
# divides by zero — the ratio is then forecast_max / epsilon, a very large
# (correctly alarming) number rather than a crash.
DISCHARGE_EPSILON = 0.01

LOW_BAND_MAX = 35.0  # score < this -> LOW
HIGH_BAND_MIN = 60.0  # score > this -> HIGH; in between (inclusive) -> WATCH

MONSOON_MONTHS = (7, 8, 9)

DISCLAIMER = (
    "Heuristic research indicator, NOT an official flood warning — consult "
    "NDMA/PMD for real alerts."
)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def band_for_score(score: float) -> str:
    if score < LOW_BAND_MAX:
        return "LOW"
    if score > HIGH_BAND_MIN:
        return "HIGH"
    return "WATCH"


def compute_anomaly_ratio(baseline_median: float, forecast_max: float, epsilon: float = DISCHARGE_EPSILON) -> float:
    return forecast_max / max(baseline_median, epsilon)


def compute_components(
    *,
    anomaly_ratio: float,
    rain_3day_mm: float,
    rain_intensity_mm: float,
    river_exposure: float,
    month: int,
) -> dict:
    """The 5 Flood Risk Index components, each clamped to [0, 1].
    See docs/FLOOD_RISK.md for the justification of every divisor."""
    return {
        "discharge": clamp01((anomaly_ratio - 1.0) / 1.5),
        "rain_3day": clamp01(rain_3day_mm / 100.0),
        "rain_intensity": clamp01(rain_intensity_mm / 60.0),
        "exposure": clamp01(river_exposure),
        "monsoon": 1.0 if month in MONSOON_MONTHS else 0.3,
    }


def compute_score(components: dict, weights: dict) -> float:
    return 100.0 * sum(weights[key] * components[key] for key in components)


class FloodDischargeClient:
    """Fetches the raw GloFAS daily river-discharge series for one
    coordinate. Kept separate from FloodService so tests can substitute a
    fake client (see app/dependencies.py get_flood_discharge_client) without
    ever making a real HTTP call — mirrors WeatherService's role in
    MapOverviewService."""

    def __init__(self, timeout_seconds: float | None = None):
        settings = get_settings()
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.weather_timeout_seconds

    def fetch(self, lat: float, lon: float) -> dict:
        """Returns {"dates": [...37 ISO dates...], "values": [...37 floats...]}."""
        last_status = None
        for _ in range(MAX_ATTEMPTS):
            try:
                response = requests.get(
                    FLOOD_API_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "daily": "river_discharge",
                        "past_days": PAST_DAYS,
                        "forecast_days": FORECAST_DAYS,
                    },
                    timeout=self._timeout,
                )
            except requests.Timeout as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Flood provider request timed out.",
                ) from exc
            except requests.RequestException as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Could not reach the flood provider.",
                ) from exc

            if response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Flood provider rejected the request.",
                )

            data = response.json()
            try:
                daily = data["daily"]
                dates = list(daily["time"])
                values = [float(v) if v is not None else 0.0 for v in daily["river_discharge"]]
            except (KeyError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from flood provider.",
                ) from exc
            return {"dates": dates, "values": values}

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Flood provider returned {last_status} after retries.",
        )


def _split_series(dates: list[str], values: list[float]) -> dict:
    """Splits the combined past+forecast series into its two halves. Uses
    fixed slice positions (first PAST_DAYS entries, last FORECAST_DAYS
    entries) rather than searching for "today" by date string, since that is
    exactly how past_days/forecast_days assemble the response (confirmed by
    a real test call — see module docstring) and is robust to the server's
    timezone/date rounding."""
    past_values = values[:PAST_DAYS]
    forecast_dates, forecast_values = dates[-FORECAST_DAYS:], values[-FORECAST_DAYS:]
    return {
        "all_dates": dates,
        "all_values": values,
        "baseline_median": statistics.median(past_values) if past_values else 0.0,
        "forecast_max": max(forecast_values) if forecast_values else 0.0,
        "forecast_dates": forecast_dates,
        "forecast_values": forecast_values,
    }


class FloodService:
    """Aggregates GloFAS discharge + rainfall forecast into a per-district
    Flood Risk Index for all districts, cached as one whole-response unit
    (mirrors MapOverviewService) for `ttl_seconds` (FLOOD_CACHE_TTL_SECONDS).
    A single district's discharge or rain-forecast failure degrades that
    district to status "unavailable" and never fails the whole response."""

    def __init__(
        self,
        discharge_client: FloodDischargeClient,
        weather_service: WeatherService,
        ttl_seconds: int = 3600,
        weights: dict | None = None,
    ):
        self._discharge_client = discharge_client
        self._weather_service = weather_service
        self._ttl_seconds = ttl_seconds
        settings = get_settings()
        self._weights = weights or {
            "discharge": settings.flood_w_discharge,
            "rain_3day": settings.flood_w_rain_3day,
            "rain_intensity": settings.flood_w_rain_intensity,
            "exposure": settings.flood_w_exposure,
            "monsoon": settings.flood_w_monsoon,
        }
        self._cache: tuple[float, dict[str, dict]] | None = None

    def _compute_district(self, name: str, params: dict, month: int) -> dict:
        try:
            series = self._discharge_client.fetch(params["lat"], params["lon"])
            split = _split_series(series["dates"], series["values"])
        except Exception:
            flood_api_failures_total.inc()
            logger.warning("Flood discharge unavailable for %s", name)
            return {"district": name, "province": params["province"], "status": "unavailable"}

        try:
            forecast = self._weather_service.fetch_forecast(name, days=RAIN_FORECAST_DAYS)
            rain_values = [day["rainfall_mm"] for day in forecast]
        except Exception:
            logger.warning("Rain forecast unavailable for %s in flood overview", name)
            return {"district": name, "province": params["province"], "status": "unavailable"}

        anomaly_ratio = compute_anomaly_ratio(split["baseline_median"], split["forecast_max"])
        rain_3day_mm = sum(rain_values)
        rain_intensity_mm = max(rain_values) if rain_values else 0.0
        components = compute_components(
            anomaly_ratio=anomaly_ratio,
            rain_3day_mm=rain_3day_mm,
            rain_intensity_mm=rain_intensity_mm,
            river_exposure=params["river_exposure"],
            month=month,
        )
        score = compute_score(components, self._weights)

        return {
            "district": name,
            "province": params["province"],
            "status": "ok",
            "score": round(score, 1),
            "band": band_for_score(score),
            "components": {k: round(v, 3) for k, v in components.items()},
            "discharge": {
                "unit": "m3/s",
                "dates": split["all_dates"],
                "values": [round(v, 2) for v in split["all_values"]],
                "baseline_median": round(split["baseline_median"], 2),
                "forecast_max": round(split["forecast_max"], 2),
                "anomaly_ratio": round(anomaly_ratio, 2),
            },
            "rain": {
                "dates": [day["date"] for day in forecast],
                "values_mm": [round(v, 1) for v in rain_values],
                "cumulative_3day_mm": round(rain_3day_mm, 1),
                "max_day_mm": round(rain_intensity_mm, 1),
            },
        }

    def _compute(self) -> dict[str, dict]:
        month = datetime.now(timezone.utc).month
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FLOOD_REQUESTS) as pool:
            futures = {
                pool.submit(self._compute_district, name, params, month): name
                for name, params in DISTRICTS.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()
        return results

    def _get_cached(self) -> dict[str, dict]:
        now = time.monotonic()
        if self._cache is not None and (now - self._cache[0]) < self._ttl_seconds:
            return self._cache[1]
        result = self._compute()
        self._cache = (now, result)
        return result

    def get_overview(self) -> dict:
        """Trimmed per-district summaries (no daily series) for the map
        choropleth and the dashboard alert card."""
        by_district = self._get_cached()
        districts = []
        for name, entry in by_district.items():
            if entry["status"] != "ok":
                districts.append({"district": name, "province": entry["province"], "status": "unavailable"})
                continue
            districts.append(
                {
                    "district": name,
                    "province": entry["province"],
                    "status": "ok",
                    "score": entry["score"],
                    "band": entry["band"],
                    "components": entry["components"],
                    "anomaly_ratio": entry["discharge"]["anomaly_ratio"],
                    "rain_3day_mm": entry["rain"]["cumulative_3day_mm"],
                }
            )
        return {
            "generated_at": datetime.now(timezone.utc),
            "ttl_seconds": self._ttl_seconds,
            "weights": self._weights,
            "bands": {"low_max": LOW_BAND_MAX, "high_min": HIGH_BAND_MIN},
            "disclaimer": DISCLAIMER,
            "districts": districts,
        }

    def get_band_for(self, district: str) -> str | None:
        """Best-effort lookup of a district's current flood band from the
        cached overview — never raises. Used by POST /api/v1/predict's flood
        override: if this returns None (unknown district, or the flood
        provider was unavailable), the caller skips the override silently
        rather than blocking a prediction on the flood API."""
        try:
            by_district = self._get_cached()
        except Exception:
            logger.warning("Flood overview unavailable while resolving band for %s", district)
            return None
        entry = by_district.get(district)
        if entry is None or entry["status"] != "ok":
            return None
        return entry["band"]

    def get_district(self, district: str) -> dict:
        """Full per-district detail (daily discharge + rain series,
        component breakdown) for the map's flood detail panel."""
        validate_district(district)
        by_district = self._get_cached()
        entry = by_district[district]
        if entry["status"] != "ok":
            return {
                "district": district,
                "province": entry["province"],
                "status": "unavailable",
                "disclaimer": DISCLAIMER,
            }
        return {**entry, "disclaimer": DISCLAIMER}
