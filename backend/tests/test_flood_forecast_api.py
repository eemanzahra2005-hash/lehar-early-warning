"""LEHAR Phase 2.5: GET /api/v1/flood/forecast/{district}.

Offline throughout — the endpoint's dependency is overridden with a
FloodForecastService pointed at the committed three-district ONNX fixture,
with fake upstream clients. No network, no torch, no trained model.
"""

import pytest

from app.dependencies import get_flood_forecast_service
from app.main import app
from app.services.flood import DISCLAIMER
from app.services.flood_forecast import FloodForecastService
from ml.flood_dl.features import HORIZONS, WINDOW_DAYS
from tests.test_flood_forecast_service import (
    FIXTURE_ROOT,
    FIXTURE_VERSION,
    FakeDischargeClient,
    FakeWeatherService,
)

FIXTURE_DISTRICT = "Lahore"


@pytest.fixture
def forecast_enabled():
    """Point the endpoint at the fixture model, with the feature ON."""
    service = FloodForecastService(
        FakeDischargeClient(),
        FakeWeatherService(),
        model_root=FIXTURE_ROOT,
        version="latest",
        enabled=True,
    )
    app.dependency_overrides[get_flood_forecast_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_flood_forecast_service, None)


@pytest.fixture
def forecast_disabled():
    service = FloodForecastService(
        FakeDischargeClient(),
        FakeWeatherService(),
        model_root=FIXTURE_ROOT,
        version="latest",
        enabled=False,
    )
    app.dependency_overrides[get_flood_forecast_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_flood_forecast_service, None)


def test_forecast_endpoint_returns_observed_and_predicted_series(client, forecast_enabled):
    response = client.get(f"/api/v1/flood/forecast/{FIXTURE_DISTRICT}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["district"] == FIXTURE_DISTRICT
    assert body["model_version"] == FIXTURE_VERSION
    assert body["lead_time_hours"] == 24
    assert body["horizons_days"] == list(HORIZONS)
    assert len(body["observed"]["values"]) == WINDOW_DAYS
    assert len(body["predicted"]["values"]) == len(HORIZONS)
    assert body["observed"]["unit"] == body["predicted"]["unit"] == "m3/s"
    assert set(body["components"]) == {"discharge", "rain_3day", "rain_intensity", "exposure", "monsoon"}


def test_forecast_endpoint_carries_the_mandated_disclaimer(client, forecast_enabled):
    """CLAUDE.md rule 12 — every surface that can show a flood state."""
    body = client.get(f"/api/v1/flood/forecast/{FIXTURE_DISTRICT}").json()
    assert body["disclaimer"] == DISCLAIMER
    assert "NDMA" in body["disclaimer"]


def test_forecast_endpoint_says_the_model_is_trained_on_real_data(client, forecast_enabled):
    """CLAUDE.md rule 13 works both ways: this model is the exception, and
    the response has to say so rather than let a reader assume synthetic."""
    body = client.get(f"/api/v1/flood/forecast/{FIXTURE_DISTRICT}").json()
    assert "REAL data" in body["training_data"]
    assert "Open-Meteo" in body["attribution"]


def test_forecast_endpoint_is_503_when_the_feature_is_disabled(client, forecast_disabled):
    response = client.get(f"/api/v1/flood/forecast/{FIXTURE_DISTRICT}")
    assert response.status_code == 503
    assert "FLOOD_DL_ENABLED" in response.json()["detail"]


def test_forecast_endpoint_is_503_when_no_model_is_registered(client, tmp_path):
    service = FloodForecastService(
        FakeDischargeClient(), FakeWeatherService(), model_root=tmp_path, version="latest", enabled=True
    )
    app.dependency_overrides[get_flood_forecast_service] = lambda: service
    try:
        response = client.get(f"/api/v1/flood/forecast/{FIXTURE_DISTRICT}")
        assert response.status_code == 503
        assert "No flood lead-time model is registered" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_flood_forecast_service, None)


def test_forecast_endpoint_is_503_for_a_district_the_model_never_saw(client, forecast_enabled):
    response = client.get("/api/v1/flood/forecast/Multan")
    assert response.status_code == 503
    assert "not part of the training set" in response.json()["detail"]


def test_forecast_endpoint_rejects_an_unknown_district(client, forecast_enabled):
    response = client.get("/api/v1/flood/forecast/Atlantis")
    assert response.status_code in (400, 404)


def test_the_existing_flood_endpoints_are_unchanged(client, forecast_enabled):
    """CLAUDE.md rule 1: Phase 2.5 is additive. Flood Watch keeps working
    exactly as it did, whether or not the lead-time model is enabled."""
    overview = client.get("/api/v1/flood/overview")
    assert overview.status_code == 200
    assert overview.json()["disclaimer"] == DISCLAIMER

    detail = client.get(f"/api/v1/flood/district/{FIXTURE_DISTRICT}")
    assert detail.status_code == 200
    assert "forecast" not in detail.json()
