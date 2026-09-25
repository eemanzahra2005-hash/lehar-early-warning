"""Tests for POST /api/v1/compare."""

from app.dependencies import get_weather_service
from app.main import app


def test_compare_returns_results_for_each_district(client):
    response = client.post(
        "/api/v1/compare",
        json={
            "districts": ["Lahore", "Multan"],
            "crop_type": "wheat",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 300.0,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 2
    for result in body["results"]:
        assert result["error"] is None
        assert result["weather"]["temperature_c"] == 30.0  # from FakeWeatherService
        assert result["recommendation_mm"] >= 0
        assert result["model_version"]
        assert result["risk"] is not None
        assert result["risk"]["band"] in ("LOW", "MODERATE", "HIGH")


def test_compare_unknown_district_is_a_per_district_error_not_a_500(client):
    response = client.post(
        "/api/v1/compare",
        json={
            "districts": ["Lahore", "Atlantis"],
            "crop_type": "wheat",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 300.0,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    ok = next(r for r in body["results"] if r["district"] == "Lahore")
    bad = next(r for r in body["results"] if r["district"] == "Atlantis")
    assert ok["error"] is None
    assert bad["error"] is not None
    assert bad["recommendation_mm"] is None
    assert bad["risk"] is None


def test_compare_rejects_fewer_than_two_districts(client):
    response = client.post(
        "/api/v1/compare",
        json={
            "districts": ["Lahore"],
            "crop_type": "wheat",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 300.0,
        },
    )

    assert response.status_code == 422


def test_compare_rejects_more_than_six_districts(client):
    response = client.post(
        "/api/v1/compare",
        json={
            "districts": ["Lahore", "Multan", "Karachi", "Peshawar", "Quetta", "Sukkur", "Sialkot"],
            "crop_type": "wheat",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 300.0,
        },
    )

    assert response.status_code == 422


def test_compare_rejects_unknown_crop(client):
    response = client.post(
        "/api/v1/compare",
        json={
            "districts": ["Lahore", "Multan"],
            "crop_type": "unobtainium",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 300.0,
        },
    )

    assert response.status_code == 400


class OneFailingWeatherService:
    FAILING_DISTRICT = "Multan"

    def fetch(self, district: str) -> dict:
        if district == self.FAILING_DISTRICT:
            raise RuntimeError("simulated outage")
        return {"temperature_c": 30.0, "humidity_pct": 45.0, "rainfall_mm": 2.0, "evapotranspiration_mm": 5.0}

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        raise NotImplementedError


def test_compare_tolerates_one_districts_weather_failure(client):
    app.dependency_overrides[get_weather_service] = lambda: OneFailingWeatherService()
    try:
        response = client.post(
            "/api/v1/compare",
            json={
                "districts": ["Lahore", "Multan"],
                "crop_type": "wheat",
                "soil_moisture_pct": 25.0,
                "canal_flow_cusecs": 300.0,
            },
        )
    finally:
        app.dependency_overrides.pop(get_weather_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    ok = next(r for r in body["results"] if r["district"] == "Lahore")
    failed = next(r for r in body["results"] if r["district"] == "Multan")
    assert ok["error"] is None
    assert failed["error"] is not None
    assert failed["recommendation_mm"] is None
