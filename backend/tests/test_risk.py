"""Tests for the Farm Risk Score (Phase 6): the pure-arithmetic formula in
app/services/risk.py, hitting every band, plus its presence in
POST /api/v1/predict and GET /api/v1/map/overview responses.
"""

import pytest

from app.services.risk import band_for_score, clamp01, compute_components, compute_score

DEFAULT_WEIGHTS = {
    "moisture_deficit": 0.35,
    "et0_demand": 0.20,
    "heat_stress": 0.15,
    "water_scarcity": 0.15,
    "rain_relief": 0.15,
}


# --- clamp01 -----------------------------------------------------------------

def test_clamp01_bounds():
    assert clamp01(-5.0) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(5.0) == 1.0


# --- Components ----------------------------------------------------------------

def test_components_all_zero_at_comfortable_conditions():
    components = compute_components(
        soil_moisture_pct=35.0,
        evapotranspiration_mm=5.0,
        temperature_c=35.0,
        canal_flow_cusecs=300.0,
        rainfall_mm=0.0,
    )
    assert components == {
        "moisture_deficit": 0.0,
        "et0_demand": 0.0,
        "heat_stress": 0.0,
        "water_scarcity": 0.0,
        "rain_relief": 0.0,
    }


def test_components_clamp_to_1_at_extreme_stress():
    components = compute_components(
        soil_moisture_pct=0.0,  # (35-0)/25 = 1.4 -> clamped to 1.0
        evapotranspiration_mm=15.0,  # (15-5)/5 = 2.0 -> clamped to 1.0
        temperature_c=50.0,  # (50-35)/10 = 1.5 -> clamped to 1.0
        canal_flow_cusecs=0.0,  # (300-0)/300 = 1.0
        rainfall_mm=100.0,  # 100/20 = 5.0 -> clamped to 1.0
    )
    assert components == {
        "moisture_deficit": 1.0,
        "et0_demand": 1.0,
        "heat_stress": 1.0,
        "water_scarcity": 1.0,
        "rain_relief": 1.0,
    }


def test_components_never_go_negative_on_the_comfortable_side():
    # Values on the "wetter/cooler than the formula's floor" side of each
    # divisor must clamp to 0.0, never a negative number.
    components = compute_components(
        soil_moisture_pct=100.0,
        evapotranspiration_mm=0.0,
        temperature_c=0.0,
        canal_flow_cusecs=1000.0,
        rainfall_mm=0.0,
    )
    assert components["moisture_deficit"] == 0.0
    assert components["et0_demand"] == 0.0
    assert components["heat_stress"] == 0.0
    assert components["water_scarcity"] == 0.0


# --- Score + bands ---------------------------------------------------------------

def test_score_hits_low_band():
    components = compute_components(
        soil_moisture_pct=40.0,
        evapotranspiration_mm=3.0,
        temperature_c=28.0,
        canal_flow_cusecs=400.0,
        rainfall_mm=5.0,
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == 0.0
    assert band_for_score(score) == "LOW"


def test_score_hits_moderate_band():
    # moisture_deficit=(35-20)/25=0.6, et0_demand=0, heat_stress=0,
    # water_scarcity=0, rain_relief=0
    # score = 100 * (0.35*0.6) = 21.0 -> still LOW; bump ET0 too to reach MODERATE.
    components = compute_components(
        soil_moisture_pct=20.0,
        evapotranspiration_mm=8.0,  # (8-5)/5 = 0.6
        temperature_c=35.0,
        canal_flow_cusecs=300.0,
        rainfall_mm=0.0,
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == pytest.approx(33.0)  # 100 * (0.35*0.6 + 0.20*0.6) = 100*(0.21+0.12) = 33.0
    assert band_for_score(score) == "LOW"  # 33.0 < 34 -> still LOW, confirms boundary math

    # Push moisture_deficit slightly further to cross into MODERATE.
    components2 = compute_components(
        soil_moisture_pct=15.0,  # (35-15)/25 = 0.8
        evapotranspiration_mm=8.0,
        temperature_c=35.0,
        canal_flow_cusecs=300.0,
        rainfall_mm=0.0,
    )
    score2 = compute_score(components2, DEFAULT_WEIGHTS)
    assert score2 == 40.0  # 100 * (0.35*0.8 + 0.20*0.6) = 100*(0.28+0.12) = 40.0
    assert band_for_score(score2) == "MODERATE"


def test_score_hits_high_band_at_max_inputs():
    components = compute_components(
        soil_moisture_pct=0.0,
        evapotranspiration_mm=15.0,
        temperature_c=50.0,
        canal_flow_cusecs=0.0,
        rainfall_mm=0.0,
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == pytest.approx(85.0)  # 100 * (0.35+0.20+0.15+0.15), rain_relief=0 so nothing subtracted
    assert band_for_score(score) == "HIGH"


def test_rain_relief_is_subtracted_and_can_zero_out_the_score():
    components = compute_components(
        soil_moisture_pct=15.0,
        evapotranspiration_mm=8.0,
        temperature_c=35.0,
        canal_flow_cusecs=300.0,
        rainfall_mm=100.0,  # clamps rain_relief to 1.0
    )
    # From test_score_hits_moderate_band, the additive sum before rain_relief
    # was 0.40 (moisture_deficit=0.8, et0_demand=0.6) -> 0.35*0.8 + 0.20*0.6 = 0.40
    # minus 0.15*1.0 = 0.25 -> score = 25.0
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == pytest.approx(25.0)
    assert band_for_score(score) == "LOW"


def test_score_never_goes_negative_even_with_large_rain_relief():
    components = compute_components(
        soil_moisture_pct=35.0,
        evapotranspiration_mm=5.0,
        temperature_c=35.0,
        canal_flow_cusecs=300.0,
        rainfall_mm=200.0,
    )
    score = compute_score(components, DEFAULT_WEIGHTS)
    assert score == 0.0


def test_band_boundaries_are_exact():
    assert band_for_score(33.9) == "LOW"
    assert band_for_score(34.0) == "MODERATE"
    assert band_for_score(66.0) == "MODERATE"
    assert band_for_score(66.1) == "HIGH"


# --- Integration: POST /api/v1/predict --------------------------------------

def test_predict_response_includes_risk(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Multan",
            "crop_type": "cotton",
            "soil_moisture_pct": 15.0,
            "canal_flow_cusecs": 100.0,
            "use_live_weather": False,
            "manual_temperature_c": 40.0,
            "manual_humidity_pct": 20.0,
            "manual_rainfall_mm": 0.0,
            "manual_evapotranspiration_mm": 9.0,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk"] is not None
    assert body["risk"]["band"] in ("LOW", "MODERATE", "HIGH")
    assert 0.0 <= body["risk"]["score"] <= 100.0
    assert set(body["risk"]["components"].keys()) == set(DEFAULT_WEIGHTS.keys())


def test_predict_risk_is_computed_even_on_sensor_fault_fallback(client):
    """Risk is pure arithmetic on inputs, independent of the ML model — it
    must still be populated when the model is bypassed entirely."""
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
    assert body["risk"] is not None


# --- Integration: GET /api/v1/map/overview ------------------------------------

def test_map_overview_includes_risk_per_district(client):
    response = client.get("/api/v1/map/overview")

    assert response.status_code == 200
    body = response.json()
    sample = next(d for d in body["districts"] if d["district"] == "Lahore")
    assert sample["status"] == "ok"
    assert sample["risk"] is not None
    assert sample["risk"]["band"] in ("LOW", "MODERATE", "HIGH")
