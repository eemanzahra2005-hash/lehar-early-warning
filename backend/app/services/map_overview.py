"""Aggregated map overview: live weather + a default-conditions irrigation
recommendation for all districts (backend/ml/districts.py).

Weather is fetched concurrently with a bounded worker pool (never more than
MAX_CONCURRENT_WEATHER_REQUESTS in flight at once, out of courtesy to the
free Open-Meteo API) and individual district failures are tolerated — a
single slow/broken district never fails the whole response. The computed
result is cached in memory for `ttl_seconds` (MAP_OVERVIEW_TTL_SECONDS) since
walking all districts on every request would be wasteful for a value that
changes slowly.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.services.ml_model import ModelService
from app.services.risk import RiskService
from app.services.weather import WeatherService
from ml.districts import DISTRICTS

logger = logging.getLogger("app.map_overview")

MAX_CONCURRENT_WEATHER_REQUESTS = 8

# Documented default field conditions used to compute every district's
# recommendation on the map — NOT the real conditions of any specific field.
# canal_flow uses each district's own baseline from ml/districts.py.
DEFAULT_SOIL_MOISTURE_PCT = 25.0
DEFAULT_CROP_TYPE = "wheat"


class MapOverviewService:
    def __init__(self, weather_service: WeatherService, model_service: ModelService, ttl_seconds: int = 600):
        self._weather_service = weather_service
        self._model_service = model_service
        self._ttl_seconds = ttl_seconds
        # No external I/O / no caching needs of its own (pure arithmetic on
        # Settings' RISK_W_* weights), so a private instance is fine —
        # doesn't need to flow through dependencies.py's DI like weather/model.
        self._risk_service = RiskService()
        self._cache: tuple[float, dict] | None = None

    def _compute_district(self, name: str, params: dict) -> dict:
        try:
            weather = self._weather_service.fetch(name)
        except Exception:
            logger.warning("Weather unavailable for %s in map overview", name)
            return {
                "district": name,
                "province": params["province"],
                "weather": None,
                "recommendation_mm": None,
                "status": "unavailable",
                "risk": None,
            }

        try:
            recommendation = self._model_service.predict(
                temperature_c=weather["temperature_c"],
                humidity_pct=weather["humidity_pct"],
                rainfall_mm=weather["rainfall_mm"],
                evapotranspiration_mm=weather["evapotranspiration_mm"],
                canal_flow_cusecs=params["canal_flow_baseline_cusecs"],
                soil_moisture_pct=DEFAULT_SOIL_MOISTURE_PCT,
                district=name,
                crop_type=DEFAULT_CROP_TYPE,
            )
        except Exception:
            logger.exception("Prediction failed for %s in map overview", name)
            return {
                "district": name,
                "province": params["province"],
                "weather": weather,
                "recommendation_mm": None,
                "status": "unavailable",
                "risk": None,
            }

        # Farm Risk Score (docs/RISK_SCORE.md) on the same default field
        # conditions used for recommendation_mm above.
        risk = self._risk_service.compute(
            soil_moisture_pct=DEFAULT_SOIL_MOISTURE_PCT,
            evapotranspiration_mm=weather["evapotranspiration_mm"],
            temperature_c=weather["temperature_c"],
            canal_flow_cusecs=params["canal_flow_baseline_cusecs"],
            rainfall_mm=weather["rainfall_mm"],
        )

        return {
            "district": name,
            "province": params["province"],
            "weather": weather,
            "recommendation_mm": round(max(0.0, recommendation), 1),
            "status": "ok",
            "risk": risk,
        }

    def _compute(self) -> dict:
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WEATHER_REQUESTS) as pool:
            futures = {
                pool.submit(self._compute_district, name, params): name for name, params in DISTRICTS.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                results[name] = future.result()

        # Reassemble in DISTRICTS' fixed order rather than completion order.
        districts = [results[name] for name in DISTRICTS]

        return {
            "generated_at": datetime.now(timezone.utc),
            "ttl_seconds": self._ttl_seconds,
            "default_conditions": {
                "soil_moisture_pct": DEFAULT_SOIL_MOISTURE_PCT,
                "crop_type": DEFAULT_CROP_TYPE,
                "canal_flow_cusecs": "district baseline (see backend/ml/districts.py)",
            },
            "note": (
                "Irrigation recommendations on this map are computed with default field "
                "conditions (soil moisture 25%, wheat, each district's baseline canal flow) "
                "— not the real conditions of any specific field."
            ),
            "districts": districts,
        }

    def get_overview(self) -> dict:
        now = time.monotonic()
        if self._cache is not None and (now - self._cache[0]) < self._ttl_seconds:
            return self._cache[1]
        result = self._compute()
        self._cache = (now, result)
        return result
