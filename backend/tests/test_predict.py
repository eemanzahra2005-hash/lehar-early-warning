"""Tests for POST /api/v1/predict.

Live weather requests are served by the fake weather service (autouse
fixture in conftest.py); the ML model used is the real trained pipeline
from backend/ml/model/ (see PROGRESS.md Phase 2) — never mocked.
"""

VALID_MANUAL_WEATHER = {
    "manual_temperature_c": 32.0,
    "manual_humidity_pct": 40.0,
    "manual_rainfall_mm": 0.0,
    "manual_evapotranspiration_mm": 6.0,
}


def test_predict_with_manual_weather_returns_recommendation(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Multan",
            "crop_type": "cotton",
            "soil_moisture_pct": 25.0,
            "canal_flow_cusecs": 400.0,
            "use_live_weather": False,
            **VALID_MANUAL_WEATHER,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["irrigation_recommendation_mm"] >= 0
    assert body["source"] == "model_prediction"
    assert body["model_version"]
    assert body["weather_used"]["source"] == "manual"


def test_predict_with_live_weather_uses_mocked_service(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weather_used"]["source"] == "open-meteo"
    assert body["weather_used"]["temperature_c"] == 30.0  # from FakeWeatherService
    assert body["source"] == "model_prediction"


def test_predict_sensor_fault_uses_rule_based_fallback(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 20.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": True,
            "simulate_sensor_fault": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "fallback_rule_based"
    assert body["model_version"] is None
    expected = round(max(0.0, (35.0 - 20.0) * 0.9), 1)
    assert body["irrigation_recommendation_mm"] == expected
    assert body["reason"]


def test_predict_unknown_district_returns_400(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Atlantis",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": True,
        },
    )

    assert response.status_code == 400


def test_predict_missing_manual_weather_returns_422(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": False,
        },
    )

    assert response.status_code == 422


# --- Phase 8: physical-bounds validation on manual weather fields ----------

def test_predict_rejects_impossible_temperature_with_422(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": False,
            **{**VALID_MANUAL_WEATHER, "manual_temperature_c": 80.0},
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    # A readable message naming the offending field and the violated bound —
    # never silently accepted or clamped (see docs/DATA_VALIDATION.md).
    detail_text = str(body["detail"])
    assert "manual_temperature_c" in detail_text
    assert "55" in detail_text


def test_predict_rejects_impossible_soil_moisture_with_422(client):
    """Pre-existing bound (Phase 3), still enforced after the Phase 8 schema
    changes — impossible soil moisture (150%) never silently accepted."""
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 150.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": False,
            **VALID_MANUAL_WEATHER,
        },
    )

    assert response.status_code == 422


def test_predict_rejects_impossible_rainfall_with_422(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": False,
            **{**VALID_MANUAL_WEATHER, "manual_rainfall_mm": 5000.0},
        },
    )

    assert response.status_code == 422
