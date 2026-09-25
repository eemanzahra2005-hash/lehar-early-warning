"""Tests for GET /api/v1/map/overview.

Uses the same fake-weather-service override pattern as conftest.py's
autouse fixture, but swaps in a custom fake for one test to prove a single
district's weather failure never turns into a 500 for the whole response.
"""

from app.dependencies import get_model_service, get_weather_service
from app.main import app
from app.services.map_overview import MapOverviewService
from ml.districts import DISTRICTS


def test_map_overview_returns_all_districts(client):
    response = client.get("/api/v1/map/overview")

    assert response.status_code == 200
    body = response.json()
    assert len(body["districts"]) == len(DISTRICTS)
    assert body["default_conditions"]["soil_moisture_pct"] == 25.0
    assert body["default_conditions"]["crop_type"] == "wheat"
    assert "default field conditions" in body["note"]

    sample = next(d for d in body["districts"] if d["district"] == "Lahore")
    assert sample["province"] == "Punjab"
    assert sample["status"] == "ok"
    assert sample["weather"]["temperature_c"] == 30.0  # from FakeWeatherService
    assert sample["recommendation_mm"] >= 0


class CountingWeatherService:
    """Real fetch()/fetch_forecast() shape, but counts calls so the test can
    prove a second get_overview() within the TTL window doesn't refetch."""

    def __init__(self):
        self.calls = 0

    def fetch(self, district: str) -> dict:
        self.calls += 1
        return {"temperature_c": 28.0, "humidity_pct": 50.0, "rainfall_mm": 1.0, "evapotranspiration_mm": 4.0}

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        raise NotImplementedError


def test_map_overview_service_caches_within_ttl():
    """Unit-level (bypassing HTTP/DI) since the autouse fake-weather-service
    override in conftest.py creates a new instance per request, which would
    otherwise defeat MapOverviewService's own identity-keyed cache lookup —
    see app/dependencies.py's _map_overview_service_for()."""
    weather = CountingWeatherService()
    service = MapOverviewService(weather, get_model_service(), ttl_seconds=600)

    first = service.get_overview()
    second = service.get_overview()

    assert first["generated_at"] == second["generated_at"]
    assert weather.calls == len(DISTRICTS)


class PartiallyFailingWeatherService:
    """Fails for exactly one district, succeeds for every other."""

    FAILING_DISTRICT = "Gilgit"

    def fetch(self, district: str) -> dict:
        if district == self.FAILING_DISTRICT:
            raise RuntimeError("simulated weather provider outage")
        return {
            "temperature_c": 28.0,
            "humidity_pct": 50.0,
            "rainfall_mm": 1.0,
            "evapotranspiration_mm": 4.0,
        }

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        raise NotImplementedError


def test_map_overview_tolerates_one_district_failing(client):
    app.dependency_overrides[get_weather_service] = lambda: PartiallyFailingWeatherService()
    try:
        response = client.get("/api/v1/map/overview")
    finally:
        app.dependency_overrides.pop(get_weather_service, None)

    assert response.status_code == 200
    body = response.json()
    assert len(body["districts"]) == len(DISTRICTS)

    failed = next(d for d in body["districts"] if d["district"] == "Gilgit")
    assert failed["status"] == "unavailable"
    assert failed["weather"] is None
    assert failed["recommendation_mm"] is None

    ok = next(d for d in body["districts"] if d["district"] == "Lahore")
    assert ok["status"] == "ok"
    assert ok["recommendation_mm"] is not None
