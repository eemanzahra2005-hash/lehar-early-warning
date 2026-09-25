"""Tests for GET /api/v1/weather and GET /api/v1/forecast.

The weather service is replaced everywhere by the autouse
`_fake_weather_service` fixture in conftest.py, so this suite never makes a
real HTTP call.
"""


def test_weather_returns_current_conditions(client):
    response = client.get("/api/v1/weather", params={"district": "Lahore"})

    assert response.status_code == 200
    body = response.json()
    assert body["district"] == "Lahore"
    assert body["source"] == "open-meteo"
    assert "temperature_c" in body


def test_weather_unknown_district_returns_400(client):
    response = client.get("/api/v1/weather", params={"district": "Atlantis"})

    assert response.status_code == 400


def test_forecast_returns_requested_number_of_days(client):
    response = client.get("/api/v1/forecast", params={"district": "Multan", "days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["district"] == "Multan"
    assert len(body["days"]) == 5


def test_forecast_rejects_more_than_16_days(client):
    response = client.get("/api/v1/forecast", params={"district": "Multan", "days": 20})

    assert response.status_code == 422


def test_forecast_unknown_district_returns_400(client):
    response = client.get("/api/v1/forecast", params={"district": "Atlantis", "days": 5})

    assert response.status_code == 400


def test_forecast_include_demand_adds_ml_estimate_per_day(client):
    response = client.get(
        "/api/v1/forecast",
        params={"district": "Multan", "days": 4, "include_demand": True, "soil_moisture_pct": 25},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["demand_note"] is not None
    assert "25" in body["demand_note"]
    assert len(body["days"]) == 4
    for day in body["days"]:
        assert day["irrigation_estimate_mm"] is not None
        assert day["irrigation_estimate_mm"] >= 0


def test_forecast_without_include_demand_omits_estimate(client):
    response = client.get("/api/v1/forecast", params={"district": "Multan", "days": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["demand_note"] is None
    for day in body["days"]:
        assert day["irrigation_estimate_mm"] is None
