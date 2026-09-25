"""Tests for Phase 16 live soil moisture (docs/SOIL_MOISTURE.md).

Covers the pure depth-weighting / unit-mapping / latest-hour helpers
(app/services/soil.py), WeatherService.fetch_soil_moisture against a
monkeypatched requests.get (never a real HTTP call), the additive
POST /predict contract including the manual fallback path,
GET /api/v1/soil-moisture, assistant grounding, and the Predict page toggle
markup. Everywhere else, conftest.py's FakeWeatherService serves layers
0.20 / 0.22 / 0.24 m³/m³, i.e. a live value of 23.2%.
"""

from datetime import datetime, timezone

import pytest
import requests
from fastapi import HTTPException

from app.dependencies import get_weather_service
from app.main import app
from app.services.soil import (
    LAYER_THICKNESS_CM,
    LIVE_LABEL,
    SOURCE_LIVE,
    SOURCE_MANUAL,
    build_reading,
    depth_weighted_root_zone,
    latest_complete_hour,
    to_soil_moisture_pct,
)
from app.services.weather import WeatherService

# conftest.py's FAKE_SOIL_LAYERS mapped into model space.
CONFTEST_LIVE_SOIL_PCT = 23.2

L1, L2, L3 = "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm"

# 08:23 UTC == 13:23 in Asia/Karachi (utc_offset_seconds=18000).
NOW_UTC = datetime(2026, 9, 15, 8, 23, tzinfo=timezone.utc)
NOW_LOCAL = datetime(2026, 9, 15, 13, 23)
HOURS = ["2026-09-15T12:00", "2026-09-15T13:00", "2026-09-15T14:00"]


def _hourly(l1, l2, l3, times=HOURS):
    return {"time": times, L1: l1, L2: l2, L3: l3}


# --- Depth-weighted root-zone average ---------------------------------------

def test_layer_weights_are_layer_thickness_in_cm():
    assert LAYER_THICKNESS_CM == {L1: 2.0, L2: 6.0, L3: 18.0}


def test_depth_weighted_root_zone_uses_2_6_18_cm_weights():
    layers = {L1: 0.10, L2: 0.20, L3: 0.30}
    # (2*0.10 + 6*0.20 + 18*0.30) / 26 = 6.8 / 26
    assert depth_weighted_root_zone(layers) == pytest.approx(6.8 / 26)


def test_depth_weighted_root_zone_of_uniform_profile_is_that_value():
    assert depth_weighted_root_zone(dict.fromkeys(LAYER_THICKNESS_CM, 0.25)) == pytest.approx(0.25)


def test_dry_surface_skin_does_not_dominate_like_a_plain_mean_would():
    # A dried-out surface over a still-wet root zone (e.g. a day after rain).
    layers = {L1: 0.05, L2: 0.30, L3: 0.30}
    weighted = depth_weighted_root_zone(layers)
    plain_mean = sum(layers.values()) / 3
    assert weighted == pytest.approx(7.3 / 26)  # (0.1 + 1.8 + 5.4) / 26
    assert weighted > plain_mean


# --- Unit mapping: m³/m³ -> soil_moisture_pct (volumetric %) ----------------

@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(0.225, 22.5), (0.0, 0.0), (0.4567, 45.7), (1.2, 100.0), (-0.01, 0.0)],
)
def test_to_soil_moisture_pct_is_volumetric_percent_rounded_and_clamped(fraction, expected):
    assert to_soil_moisture_pct(fraction) == expected


def test_build_reading_maps_real_open_meteo_values_into_model_space():
    # Real Multan values returned by Open-Meteo for 2026-09-15 06:00 local
    # (the example worked through in docs/SOIL_MOISTURE.md).
    reading = build_reading({L1: 0.193, L2: 0.213, L3: 0.230}, "2026-09-15T06:00")

    assert reading["layers"]["root_zone"] == pytest.approx(5.804 / 26, abs=1e-4)
    assert reading["soil_moisture_pct"] == 22.3
    assert reading["source"] == SOURCE_LIVE
    assert reading["label"] == LIVE_LABEL
    assert reading["layers"]["unit"] == "m³/m³"
    assert reading["layers"]["observed_at"] == "2026-09-15T06:00"
    assert reading["layers"][L3] == 0.230


# --- Latest available hour --------------------------------------------------

def test_latest_complete_hour_ignores_future_forecast_hours():
    hourly = _hourly([0.1, 0.2, 0.9], [0.1, 0.2, 0.9], [0.1, 0.2, 0.9])
    observed_at, layers = latest_complete_hour(hourly, NOW_LOCAL)
    assert observed_at == "2026-09-15T13:00"
    assert layers == {L1: 0.2, L2: 0.2, L3: 0.2}


def test_latest_complete_hour_skips_hours_with_a_missing_layer():
    hourly = _hourly([0.1, 0.2, 0.3], [0.1, None, 0.3], [0.1, 0.2, 0.3])
    observed_at, _ = latest_complete_hour(hourly, NOW_LOCAL)
    assert observed_at == "2026-09-15T12:00"


def test_latest_complete_hour_returns_none_when_no_hour_is_usable():
    hourly = _hourly([None] * 3, [None] * 3, [None] * 3)
    assert latest_complete_hour(hourly, NOW_LOCAL) is None


# --- WeatherService.fetch_soil_moisture (requests.get monkeypatched) --------

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


def _open_meteo_payload(hourly):
    """Same shape as a real Open-Meteo response, confirmed by a live call for
    Multan on 2026-09-15: district-local hourly timestamps plus
    utc_offset_seconds."""
    return {
        "latitude": 30.123022,
        "longitude": 71.49533,
        "timezone": "Asia/Karachi",
        "utc_offset_seconds": 18000,
        "hourly_units": {"time": "iso8601", L1: "m³/m³", L2: "m³/m³", L3: "m³/m³"},
        "hourly": hourly,
    }


def test_weather_service_fetch_soil_moisture_picks_latest_hour_and_maps_it(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"params": params, "timeout": timeout})
        return _FakeResponse(200, _open_meteo_payload(_hourly([0.19, 0.20, 0.99], [0.21, 0.22, 0.99], [0.23, 0.24, 0.99])))

    monkeypatch.setattr("app.services.weather.requests.get", fake_get)
    reading = WeatherService(timeout_seconds=3.5, cache_ttl_seconds=300).fetch_soil_moisture("Multan", now_utc=NOW_UTC)

    # 14:00 local is still a forecast hour at 13:23 local, so 13:00 is used.
    assert reading["layers"]["observed_at"] == "2026-09-15T13:00"
    assert reading["soil_moisture_pct"] == 23.2  # (2*0.20 + 6*0.22 + 18*0.24) / 26 = 0.2323
    assert reading["source"] == SOURCE_LIVE

    params = calls[0]["params"]
    assert params["hourly"] == f"{L1},{L2},{L3}"
    assert (params["latitude"], params["longitude"]) == (30.1575, 71.5249)  # Multan, ml/districts.py
    assert params["timezone"] == "auto"
    assert calls[0]["timeout"] == 3.5  # the same weather timeout setting


def test_weather_service_soil_moisture_is_cached_within_ttl(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        calls["count"] += 1
        return _FakeResponse(200, _open_meteo_payload(_hourly([0.2] * 3, [0.2] * 3, [0.2] * 3)))

    monkeypatch.setattr("app.services.weather.requests.get", fake_get)
    service = WeatherService(timeout_seconds=1.0, cache_ttl_seconds=300)
    first = service.fetch_soil_moisture("Multan", now_utc=NOW_UTC)
    second = service.fetch_soil_moisture("Multan", now_utc=NOW_UTC)

    assert calls["count"] == 1
    assert first == second


def test_weather_service_soil_moisture_timeout_raises_clean_504(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.Timeout("upstream too slow")

    monkeypatch.setattr("app.services.weather.requests.get", fake_get)
    with pytest.raises(HTTPException) as excinfo:
        WeatherService(timeout_seconds=1.0).fetch_soil_moisture("Multan", now_utc=NOW_UTC)
    assert excinfo.value.status_code == 504


def test_weather_service_soil_moisture_with_no_usable_hour_raises_502(monkeypatch):
    payload = _open_meteo_payload(_hourly([None] * 3, [None] * 3, [None] * 3))
    monkeypatch.setattr("app.services.weather.requests.get", lambda *a, **k: _FakeResponse(200, payload))
    with pytest.raises(HTTPException) as excinfo:
        WeatherService(timeout_seconds=1.0).fetch_soil_moisture("Multan", now_utc=NOW_UTC)
    assert excinfo.value.status_code == 502


def test_weather_service_soil_moisture_malformed_response_raises_502(monkeypatch):
    monkeypatch.setattr("app.services.weather.requests.get", lambda *a, **k: _FakeResponse(200, {"hourly": {}}))
    with pytest.raises(HTTPException) as excinfo:
        WeatherService(timeout_seconds=1.0).fetch_soil_moisture("Multan", now_utc=NOW_UTC)
    assert excinfo.value.status_code == 502


# --- POST /predict: additive contract + fallback ----------------------------

MANUAL_WEATHER = {
    "manual_temperature_c": 32.0,
    "manual_humidity_pct": 40.0,
    "manual_rainfall_mm": 0.0,
    "manual_evapotranspiration_mm": 6.0,
}


def _predict_payload(**overrides):
    body = {
        "district": "Multan",
        "crop_type": "wheat",
        "soil_moisture_pct": 30.0,
        "canal_flow_cusecs": 400.0,
        "use_live_weather": False,
        **MANUAL_WEATHER,
    }
    body.update(overrides)
    return body


class _SoilOutageWeatherService:
    """Weather works but soil moisture fails — the partial-outage case."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def fetch(self, district: str) -> dict:
        return {"temperature_c": 30.0, "humidity_pct": 45.0, "rainfall_mm": 2.0, "evapotranspiration_mm": 5.0}

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        return [
            {"date": f"2026-08-{12 + i:02d}", "temperature_c": 30.0, "humidity_pct": 45.0,
             "rainfall_mm": 1.0, "evapotranspiration_mm": 5.0}
            for i in range(days)
        ]

    def fetch_soil_moisture(self, district: str) -> dict:
        raise self._exc


def test_predict_existing_request_shape_is_unchanged_and_reports_manual_source(client):
    payload = _predict_payload()
    assert "use_live_soil" not in payload  # a pre-Phase-16 request, untouched

    response = client.post("/api/v1/predict", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    for key in ("irrigation_recommendation_mm", "source", "model_version", "weather_used", "inputs_used", "risk"):
        assert key in body
    assert body["inputs_used"]["soil_moisture_pct"] == 30.0
    assert body["soil_moisture_used"] == 30.0
    assert body["soil_moisture_source"] == SOURCE_MANUAL
    assert body["soil_moisture_layers"] is None
    assert body["soil_moisture_note"] is None


def test_predict_use_live_soil_reports_value_source_and_raw_layers(client):
    response = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["soil_moisture_source"] == "live (Open-Meteo model estimate)"
    assert body["soil_moisture_used"] == CONFTEST_LIVE_SOIL_PCT
    assert body["inputs_used"]["soil_moisture_pct"] == CONFTEST_LIVE_SOIL_PCT
    assert body["soil_moisture_note"] is None
    layers = body["soil_moisture_layers"]
    assert (layers[L1], layers[L2], layers[L3]) == (0.20, 0.22, 0.24)
    assert layers["root_zone"] == pytest.approx(6.04 / 26, abs=1e-4)
    assert layers["unit"] == "m³/m³"
    assert layers["observed_at"]


def test_predict_live_soil_feeds_model_and_risk_exactly_like_that_value_entered_manually(client):
    live = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True)).json()
    manual = client.post("/api/v1/predict", json=_predict_payload(soil_moisture_pct=CONFTEST_LIVE_SOIL_PCT)).json()

    assert live["irrigation_recommendation_mm"] == manual["irrigation_recommendation_mm"]
    assert live["risk"] == manual["risk"]


def test_predict_live_soil_is_used_by_sensor_fault_fallback_rule(client):
    response = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True, simulate_sensor_fault=True))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "fallback_rule_based"
    assert body["irrigation_recommendation_mm"] == round(max(0.0, (35.0 - CONFTEST_LIVE_SOIL_PCT) * 0.9), 1)


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (HTTPException(status_code=504, detail="Weather provider request timed out."), "Weather provider request timed out."),
        (RuntimeError("internal boom"), "unexpected error"),
    ],
)
def test_predict_live_soil_failure_falls_back_to_manual_and_says_so(client, exc, reason):
    app.dependency_overrides[get_weather_service] = lambda: _SoilOutageWeatherService(exc)

    response = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True, soil_moisture_pct=30.0))

    assert response.status_code == 200, response.text  # never blocks the prediction
    body = response.json()
    assert body["source"] == "model_prediction"
    assert body["soil_moisture_source"] == SOURCE_MANUAL
    assert body["soil_moisture_used"] == 30.0
    assert body["inputs_used"]["soil_moisture_pct"] == 30.0
    assert body["soil_moisture_layers"] is None
    assert reason in body["soil_moisture_note"]
    assert "manual value" in body["soil_moisture_note"]
    assert "internal boom" not in body["soil_moisture_note"]  # never leaks internals


def test_predict_live_soil_value_is_what_gets_logged_to_history(client, register_user):
    headers = {"Authorization": f"Bearer {register_user(username='soilfarmer')}"}

    response = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True), headers=headers)
    assert response.status_code == 200, response.text

    history = client.get("/api/v1/history", headers=headers).json()
    assert len(history) == 1
    assert history[0]["soil_moisture_pct"] == CONFTEST_LIVE_SOIL_PCT


# --- GET /api/v1/soil-moisture ------------------------------------------------

def test_get_soil_moisture_returns_labelled_live_estimate(client):
    response = client.get("/api/v1/soil-moisture", params={"district": "Multan"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["district"] == "Multan"
    assert body["soil_moisture_pct"] == CONFTEST_LIVE_SOIL_PCT
    assert body["source"] == SOURCE_LIVE
    assert body["label"] == LIVE_LABEL
    assert body["layers"]["unit"] == "m³/m³"


def test_get_soil_moisture_unknown_district_returns_400(client):
    response = client.get("/api/v1/soil-moisture", params={"district": "Atlantis"})
    assert response.status_code == 400


def test_get_soil_moisture_provider_failure_is_a_clean_error(client):
    outage = HTTPException(status_code=502, detail="Could not reach the weather provider.")
    app.dependency_overrides[get_weather_service] = lambda: _SoilOutageWeatherService(outage)

    response = client.get("/api/v1/soil-moisture", params={"district": "Multan"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not reach the weather provider."


# --- Assistant grounding ------------------------------------------------------

def _mock_llm_reply(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm.requests.post",
        lambda *a, **k: _FakeResponse(200, {"message": {"content": "ok. AI-generated — not agronomic advice."}}),
    )


def test_assistant_context_includes_live_soil_moisture_value_and_source(client, monkeypatch):
    _mock_llm_reply(monkeypatch)

    response = client.post("/api/v1/assistant/chat", json={"message": "How wet is the soil in Multan?"})

    assert response.status_code == 200, response.text
    context = response.json()["context_used"]
    live = context["live_soil_moisture"]
    assert live["soil_moisture_pct"] == CONFTEST_LIVE_SOIL_PCT
    assert live["source"] == SOURCE_LIVE
    assert live["note"] == LIVE_LABEL
    assert live["layers"]["unit"] == "m³/m³"
    # The recommendation's fixed default is labelled as the assumption it is.
    recommendation = context["irrigation_recommendation"]
    assert recommendation["soil_moisture_pct"] == 25.0
    assert recommendation["soil_moisture_source"] == "default assumption (not measured)"


def test_assistant_context_omits_live_soil_moisture_when_fetch_fails(client, monkeypatch):
    _mock_llm_reply(monkeypatch)
    outage = HTTPException(status_code=504, detail="Weather provider request timed out.")
    app.dependency_overrides[get_weather_service] = lambda: _SoilOutageWeatherService(outage)

    response = client.post("/api/v1/assistant/chat", json={"message": "How wet is the soil in Multan?"})

    assert response.status_code == 200, response.text
    context = response.json()["context_used"]
    assert "live_soil_moisture" not in context
    assert "current_weather" in context  # every other section unaffected


def test_assistant_this_prediction_carries_soil_moisture_source(client, monkeypatch):
    _mock_llm_reply(monkeypatch)
    result = client.post("/api/v1/predict", json=_predict_payload(use_live_soil=True)).json()

    response = client.post(
        "/api/v1/assistant/chat",
        json={"message": "Explain this prediction.", "district": "Multan", "prediction_context": result},
    )

    assert response.status_code == 200, response.text
    this_prediction = response.json()["context_used"]["this_prediction"]
    assert this_prediction["soil_moisture_used"] == CONFTEST_LIVE_SOIL_PCT
    assert this_prediction["soil_moisture_source"] == SOURCE_LIVE


# --- Predict page toggle (static checks — there is no JS test runner) -------

def test_predict_page_has_live_soil_toggle_with_honest_label(client):
    response = client.get("/js/views/predict.js")

    assert response.status_code == 200
    js = response.text
    assert 'id="use-live-soil"' in js
    assert "Use live soil moisture" in js
    assert LIVE_LABEL in js  # identical wording to the API/assistant label
    assert SOURCE_LIVE in js
    assert "use_live_soil" in js


def test_frontend_api_client_calls_soil_moisture_endpoint(client):
    response = client.get("/js/api.js")

    assert response.status_code == 200
    assert "'/soil-moisture'" in response.text
