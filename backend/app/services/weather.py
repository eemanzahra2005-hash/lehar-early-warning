"""Open-Meteo weather client.

Open-Meteo (https://open-meteo.com/en/docs) requires no API key. District
coordinates come from ml/districts.py (SYNTHETIC lat/lon placeholders for
each district's main city) — only the weather VALUES returned by Open-Meteo
below are real, live data.

Note: Open-Meteo has no daily relative-humidity aggregate, so
fetch_forecast() derives a per-day mean from the hourly relative_humidity_2m
series instead of requesting a (nonexistent) daily humidity variable.

Phase 16: fetch_soil_moisture() reads hourly soil moisture from this same
forecast API — a weather-model estimate, not a field measurement (see
app/services/soil.py and docs/SOIL_MOISTURE.md).
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from fastapi import HTTPException, status

from app.config import get_settings
from app.metrics import weather_api_failures_total
from app.services.soil import SOIL_MOISTURE_VARIABLES, build_reading, latest_complete_hour
from app.validators import validate_district
from ml.districts import DISTRICTS

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16
# Open-Meteo's forecast API can also serve recent past days from the same
# endpoint (`past_days`), capped at 92. Used by fetch_daily_history_and_outlook.
MAX_PAST_DAYS = 92
MAX_ATTEMPTS = 3  # 1 initial attempt + 2 retries, only on 5xx responses


def _optional_float(value) -> float | None:
    """Open-Meteo returns null for a day it has no value for (the newest
    forecast hours, or a gap in the archive). Kept as None rather than
    coerced to 0.0: zero rainfall and "no reading" are different facts, and
    the flood lead-time model must refuse to run on a fabricated zero
    (CLAUDE.md rule 4)."""
    return None if value is None else float(value)


class WeatherService:
    """Fetches current + forecast weather for a district, with an in-memory
    TTL cache so repeated requests within the TTL window don't re-hit the API."""

    def __init__(self, timeout_seconds: float | None = None, cache_ttl_seconds: int | None = None):
        settings = get_settings()
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.weather_timeout_seconds
        self._cache_ttl = cache_ttl_seconds if cache_ttl_seconds is not None else settings.weather_cache_ttl_seconds
        self._cache: dict[tuple, tuple[float, object]] = {}

    def _coords_for(self, district: str) -> tuple[float, float]:
        validate_district(district)
        params = DISTRICTS[district]
        return params["lat"], params["lon"]

    def _cached_or_fetch(self, cache_key: tuple, fetch_fn):
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached[0]) < self._cache_ttl:
            return cached[1]
        result = fetch_fn()
        self._cache[cache_key] = (now, result)
        return result

    def _request(self, params: dict) -> dict:
        """Thin wrapper around _request_uncounted so every transport-level
        failure (timeout, network error, 4xx/5xx after retries) increments
        weather_api_failures_total exactly once, in one place, regardless of
        which raise site below triggered it."""
        try:
            return self._request_uncounted(params)
        except HTTPException:
            weather_api_failures_total.inc()
            raise

    def _request_uncounted(self, params: dict) -> dict:
        """GETs Open-Meteo, retrying up to 2 times on 5xx responses. Network
        errors and non-5xx failures raise a clean HTTPException immediately
        (never a raw stack trace / never leaks upstream details)."""
        last_status = None
        for _ in range(MAX_ATTEMPTS):
            try:
                response = requests.get(OPEN_METEO_URL, params=params, timeout=self._timeout)
            except requests.Timeout as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Weather provider request timed out.",
                ) from exc
            except requests.RequestException as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Could not reach the weather provider.",
                ) from exc

            if response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Weather provider rejected the request.",
                )
            return response.json()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Weather provider returned {last_status} after retries.",
        )

    def fetch(self, district: str) -> dict:
        """Current temperature/humidity + today's rainfall/ET0 for a district."""
        lat, lon = self._coords_for(district)

        def _do_fetch() -> dict:
            data = self._request(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m",
                    "daily": "precipitation_sum,et0_fao_evapotranspiration",
                    "timezone": "auto",
                    "forecast_days": 1,
                }
            )
            try:
                current = data["current"]
                daily = data["daily"]
                return {
                    "temperature_c": float(current["temperature_2m"]),
                    "humidity_pct": float(current["relative_humidity_2m"]),
                    "rainfall_mm": float(daily["precipitation_sum"][0]),
                    "evapotranspiration_mm": float(daily["et0_fao_evapotranspiration"][0]),
                }
            except (KeyError, IndexError, TypeError) as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc

        return self._cached_or_fetch(("current", district), _do_fetch)

    def fetch_soil_moisture(self, district: str, now_utc: datetime | None = None) -> dict:
        """Phase 16: latest available hourly soil moisture for a district —
        three Open-Meteo layers (m³/m³) reduced to one depth-weighted
        root-zone value in the model's soil_moisture_pct space (see
        app/services/soil.py, docs/SOIL_MOISTURE.md). Same timeout, 5xx
        retry, TTL cache, and clean-HTTPException failure contract as
        fetch() above. `now_utc` exists only so tests can pin "now"."""
        lat, lon = self._coords_for(district)

        def _do_fetch() -> dict:
            data = self._request(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": ",".join(SOIL_MOISTURE_VARIABLES),
                    "timezone": "auto",
                    # Yesterday's hours too, so there is always an earlier
                    # complete hour to fall back on (e.g. just after local
                    # midnight, or while the newest hours are still null).
                    "past_days": 1,
                    "forecast_days": 1,
                }
            )
            try:
                # timezone=auto makes the hourly timestamps district-local,
                # so "now" has to be compared on that same local clock.
                now = now_utc if now_utc is not None else datetime.now(timezone.utc)
                now_local = (now + timedelta(seconds=int(data["utc_offset_seconds"]))).replace(tzinfo=None)
                latest = latest_complete_hour(data["hourly"], now_local)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc
            if latest is None:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Weather provider has no soil moisture data for this district right now.",
                )
            observed_at, layers = latest
            return build_reading(layers, observed_at)

        return self._cached_or_fetch(("soil", district), _do_fetch)

    def fetch_daily_outlook(self, district: str, days: int = 3) -> list[dict]:
        """LEHAR Phase 2: daily MAXIMUM temperature + precipitation sum for
        the next `days` days — the two variables the HEAVY_RAIN and
        HEAT_STRESS alert rules are defined on.

        Deliberately separate from fetch_forecast() above rather than
        folded into it (CLAUDE.md rule 1 — additive): fetch_forecast serves
        the irrigation forecast page and returns temperature_2m_MEAN, which
        every existing caller and test depends on. A heat-stress alert
        needs temperature_2m_MAX — a district can average 32 C while
        peaking at 46 C — so this asks Open-Meteo for its own, cheaper
        variable set and caches it under its own key.
        """
        if days > MAX_FORECAST_DAYS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="days must be <= 16")
        lat, lon = self._coords_for(district)

        def _do_fetch() -> list[dict]:
            data = self._request(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,precipitation_sum",
                    "timezone": "auto",
                    "forecast_days": days,
                }
            )
            try:
                daily = data["daily"]
                return [
                    {
                        "date": day,
                        "temperature_max_c": float(daily["temperature_2m_max"][i]),
                        "rainfall_mm": float(daily["precipitation_sum"][i]),
                    }
                    for i, day in enumerate(daily["time"])
                ]
            except (KeyError, IndexError, TypeError) as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc

        return self._cached_or_fetch(("outlook", district, days), _do_fetch)

    def fetch_daily_history_and_outlook(
        self, district: str, past_days: int = 14, forecast_days: int = 4
    ) -> list[dict]:
        """LEHAR Phase 2.5: recent PAST days plus the next few forecast days
        of daily maximum temperature + precipitation, as one date-ordered
        series.

        The flood lead-time model (ml/flood_dl/) reads a 14-day window of
        history ending today, and then needs the rain forecast for the days
        it is predicting into. Open-Meteo serves both from one call via
        `past_days`, so this is one request rather than two.

        Additive alongside fetch_daily_outlook() rather than a change to it
        (CLAUDE.md rule 1): that method is what the HEAVY_RAIN/HEAT_STRESS
        alert rules call, it returns forecast days only, and every existing
        caller and test depends on exactly that. Same variables, same units,
        same failure contract — only the window differs, and it caches under
        its own key.

        Each entry is {"date", "temperature_max_c", "rainfall_mm"}, and
        callers align on `date` rather than on position: `past_days` counts
        days BEFORE today, so the caller must not have to know whether
        "today" landed at index 13 or 14.
        """
        if past_days + forecast_days > MAX_FORECAST_DAYS + MAX_PAST_DAYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"past_days + forecast_days must be <= {MAX_FORECAST_DAYS + MAX_PAST_DAYS}",
            )
        lat, lon = self._coords_for(district)

        def _do_fetch() -> list[dict]:
            data = self._request(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,precipitation_sum",
                    # UTC, not "auto": these values are joined by date against
                    # the GloFAS discharge series, which is on UTC days. Two
                    # series aggregated on different midnights cannot be
                    # joined by date without silently shifting one of them.
                    "timezone": "UTC",
                    "past_days": past_days,
                    "forecast_days": forecast_days,
                }
            )
            try:
                daily = data["daily"]
                return [
                    {
                        "date": day,
                        "temperature_max_c": _optional_float(daily["temperature_2m_max"][i]),
                        "rainfall_mm": _optional_float(daily["precipitation_sum"][i]),
                    }
                    for i, day in enumerate(daily["time"])
                ]
            except (KeyError, IndexError, TypeError) as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc

        return self._cached_or_fetch(("history_outlook", district, past_days, forecast_days), _do_fetch)

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        """Daily forecast for the next `days` days (<=16)."""
        if days > MAX_FORECAST_DAYS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="days must be <= 16")
        lat, lon = self._coords_for(district)

        def _do_fetch() -> list[dict]:
            data = self._request(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_mean,precipitation_sum,et0_fao_evapotranspiration",
                    "hourly": "relative_humidity_2m",
                    "timezone": "auto",
                    "forecast_days": days,
                }
            )
            try:
                daily = data["daily"]
                hourly = data["hourly"]
            except KeyError as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc

            humidity_by_date: dict[str, list[float]] = defaultdict(list)
            for timestamp, humidity in zip(hourly.get("time", []), hourly.get("relative_humidity_2m", [])):
                if humidity is not None:
                    humidity_by_date[timestamp[:10]].append(humidity)

            try:
                results = []
                for i, day in enumerate(daily["time"]):
                    humidity_values = humidity_by_date.get(day, [])
                    humidity_mean = sum(humidity_values) / len(humidity_values) if humidity_values else None
                    results.append(
                        {
                            "date": day,
                            "temperature_c": float(daily["temperature_2m_mean"][i]),
                            "humidity_pct": float(humidity_mean) if humidity_mean is not None else None,
                            "rainfall_mm": float(daily["precipitation_sum"][i]),
                            "evapotranspiration_mm": float(daily["et0_fao_evapotranspiration"][i]),
                        }
                    )
                return results
            except (KeyError, IndexError, TypeError) as exc:
                weather_api_failures_total.inc()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unexpected response from weather provider.",
                ) from exc

        return self._cached_or_fetch(("forecast", district, days), _do_fetch)
