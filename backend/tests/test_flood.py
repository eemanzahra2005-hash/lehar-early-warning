"""Tests for the Flood Watch feature (Phase 5.5): the risk-formula math in
app/services/flood.py, GET /api/v1/flood/overview + /flood/district/{name},
and the flood cross-link in POST /api/v1/predict. Everything here is offline
— the real Open-Meteo Flood API is never called (see conftest.py's autouse
_fake_flood_discharge_client fixture and README note in flood.py's module
docstring for the one real test call that confirmed the response shape).
"""

from app.dependencies import get_flood_discharge_client, get_flood_service
from app.main import app
from app.services.flood import (
    band_for_score,
    compute_anomaly_ratio,
    compute_components,
    compute_score,
)
from ml.districts import DISTRICTS

DEFAULT_WEIGHTS = {
    "discharge": 0.30,
    "rain_3day": 0.25,
    "rain_intensity": 0.15,
    "exposure": 0.20,
    "monsoon": 0.10,
}


# --- Risk formula: components + score + bands -------------------------------

def test_components_all_zero_when_nothing_is_elevated():
    components = compute_components(
        anomaly_ratio=1.0, rain_3day_mm=0.0, rain_intensity_mm=0.0, river_exposure=0.0, month=1
    )
    assert components["discharge"] == 0.0
    assert components["rain_3day"] == 0.0
    assert components["rain_intensity"] == 0.0
    assert components["exposure"] == 0.0
    assert components["monsoon"] == 0.3  # off-season floor, never 0


def test_components_clamp_to_1_when_inputs_exceed_the_divisor():
    components = compute_components(
        anomaly_ratio=10.0,  # (10-1)/1.5 = 6.0 -> clamped to 1.0
        rain_3day_mm=500.0,  # far past 100mm
        rain_intensity_mm=200.0,  # far past 60mm
        river_exposure=1.5,  # out-of-range input still clamps safely
        month=8,
    )
    assert components == {"discharge": 1.0, "rain_3day": 1.0, "rain_intensity": 1.0, "exposure": 1.0, "monsoon": 1.0}


def test_monsoon_component_is_1_in_jul_sep_and_0_3_otherwise():
    for month in (7, 8, 9):
        assert compute_components(anomaly_ratio=1, rain_3day_mm=0, rain_intensity_mm=0, river_exposure=0, month=month)["monsoon"] == 1.0
    for month in (1, 6, 10, 12):
        assert compute_components(anomaly_ratio=1, rain_3day_mm=0, rain_intensity_mm=0, river_exposure=0, month=month)["monsoon"] == 0.3


def test_score_hits_low_band():
    components = compute_components(
        anomaly_ratio=1.0, rain_3day_mm=0.0, rain_intensity_mm=0.0, river_exposure=0.0, month=1
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == 3.0  # 100 * (0.10 * 0.3)
    assert band_for_score(score) == "LOW"


def test_score_hits_watch_band():
    components = compute_components(
        anomaly_ratio=2.0, rain_3day_mm=0.0, rain_intensity_mm=0.0, river_exposure=0.5, month=8
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == 40.0  # 100 * (0.30*0.667.. + 0.20*0.5 + 0.10*1.0), see inline math below
    assert band_for_score(score) == "WATCH"


def test_score_hits_high_band_at_max_inputs():
    components = compute_components(
        anomaly_ratio=3.0, rain_3day_mm=100.0, rain_intensity_mm=60.0, river_exposure=1.0, month=8
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == 100.0  # every component maxed at 1.0 with the default weights
    assert band_for_score(score) == "HIGH"


def test_band_boundaries_are_exact():
    assert band_for_score(34.9) == "LOW"
    assert band_for_score(35.0) == "WATCH"
    assert band_for_score(60.0) == "WATCH"
    assert band_for_score(60.1) == "HIGH"


# --- Discharge anomaly math ---------------------------------------------------

def test_anomaly_ratio_is_forecast_over_baseline():
    assert compute_anomaly_ratio(baseline_median=2.0, forecast_max=4.0) == 2.0
    assert compute_anomaly_ratio(baseline_median=5.0, forecast_max=5.0) == 1.0


def test_anomaly_ratio_epsilon_floor_avoids_divide_by_zero():
    # A bone-dry riverbed (median 0 over the past 30 days) must not crash —
    # it falls back to the epsilon floor, producing a large, correctly
    # alarming ratio instead of a ZeroDivisionError.
    ratio = compute_anomaly_ratio(baseline_median=0.0, forecast_max=5.0, epsilon=0.01)
    assert ratio == 500.0
    assert compute_anomaly_ratio(baseline_median=0.0, forecast_max=0.0, epsilon=0.01) == 0.0


# --- GET /api/v1/flood/overview -----------------------------------------------

def test_flood_overview_returns_all_districts(client):
    response = client.get("/api/v1/flood/overview")

    assert response.status_code == 200
    body = response.json()
    assert len(body["districts"]) == len(DISTRICTS)
    assert body["disclaimer"]
    assert "not an official flood warning" in body["disclaimer"].lower() or "NOT an official flood warning" in body["disclaimer"]
    assert body["bands"]["low_max"] == 35.0
    assert body["bands"]["high_min"] == 60.0

    sample = next(d for d in body["districts"] if d["district"] == "Lahore")
    assert sample["status"] == "ok"
    assert sample["score"] is not None
    assert sample["band"] in ("LOW", "WATCH", "HIGH")


class OneDistrictFailingDischargeClient:
    """Fails discharge fetch for exactly one district, succeeds for every
    other — proves a single provider failure never fails the whole overview
    (mirrors PartiallyFailingWeatherService in test_map.py)."""

    FAILING_DISTRICT = "Gilgit"

    def fetch(self, lat: float, lon: float) -> dict:
        failing_params = DISTRICTS[self.FAILING_DISTRICT]
        if (lat, lon) == (failing_params["lat"], failing_params["lon"]):
            raise RuntimeError("simulated flood provider outage")
        return {"dates": [f"d{i}" for i in range(37)], "values": [1.0] * 37}


def test_flood_overview_tolerates_one_district_failing(client):
    app.dependency_overrides[get_flood_discharge_client] = lambda: OneDistrictFailingDischargeClient()
    try:
        response = client.get("/api/v1/flood/overview")
    finally:
        app.dependency_overrides.pop(get_flood_discharge_client, None)

    assert response.status_code == 200
    body = response.json()
    assert len(body["districts"]) == len(DISTRICTS)

    failed = next(d for d in body["districts"] if d["district"] == "Gilgit")
    assert failed["status"] == "unavailable"
    assert failed["score"] is None

    ok = next(d for d in body["districts"] if d["district"] == "Lahore")
    assert ok["status"] == "ok"
    assert ok["score"] is not None


def test_flood_district_detail_includes_daily_series(client):
    response = client.get("/api/v1/flood/district/Lahore")

    assert response.status_code == 200
    body = response.json()
    assert body["district"] == "Lahore"
    assert body["status"] == "ok"
    assert len(body["discharge"]["dates"]) == 37
    assert len(body["discharge"]["values"]) == 37
    assert len(body["rain"]["dates"]) == 3
    assert set(body["components"].keys()) == set(DEFAULT_WEIGHTS.keys())
    assert body["disclaimer"]


def test_flood_district_detail_unknown_district_returns_400(client):
    response = client.get("/api/v1/flood/district/Atlantis")

    assert response.status_code == 400


# --- Cross-link with POST /api/v1/predict -------------------------------------

class FixedBandFloodService:
    """Minimal fake exposing only what predict.py actually calls."""

    def __init__(self, band):
        self._band = band

    def get_band_for(self, district: str):
        return self._band


def test_predict_overridden_to_zero_when_flood_band_is_high(client):
    app.dependency_overrides[get_flood_service] = lambda: FixedBandFloodService("HIGH")
    try:
        response = client.post(
            "/api/v1/predict",
            json={
                "district": "Dera Ghazi Khan",
                "crop_type": "wheat",
                "soil_moisture_pct": 15.0,  # would otherwise recommend well above 0
                "canal_flow_cusecs": 300.0,
                "use_live_weather": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_flood_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["irrigation_recommendation_mm"] == 0.0
    assert body["source"] == "rule_flood_override"
    assert body["reason"]
    assert body["model_raw_mm"] is not None
    assert body["model_raw_mm"] > 0.0  # the model's real, un-overridden output is preserved


def test_predict_not_overridden_when_flood_band_is_low(client):
    app.dependency_overrides[get_flood_service] = lambda: FixedBandFloodService("LOW")
    try:
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
    finally:
        app.dependency_overrides.pop(get_flood_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "model_prediction"
    assert body["model_raw_mm"] is None


def test_predict_not_blocked_when_flood_data_unavailable(client):
    """get_band_for() returning None (flood provider unavailable, or an
    unrecognized district) must silently skip the override — never block or
    fail a prediction."""
    app.dependency_overrides[get_flood_service] = lambda: FixedBandFloodService(None)
    try:
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
    finally:
        app.dependency_overrides.pop(get_flood_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "model_prediction"
    assert body["model_raw_mm"] is None
