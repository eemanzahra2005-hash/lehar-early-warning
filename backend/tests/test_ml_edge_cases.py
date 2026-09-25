"""Phase 11 ML edge-case coverage: model load for the current registry
version, and prediction-bounds sanity across a broad district/crop grid.

Quality-gate boundary behavior (exactly-at-tolerance) is already covered by
test_pipeline.py's test_gate_boundary_exactly_at_tolerance_passes — not
duplicated here."""

from app.services.ml_model import ModelService
from ml.districts import DISTRICTS
from ml.generate_data import CROPS
from ml.registry import get_latest_version

VALID_MANUAL_WEATHER = {
    "manual_temperature_c": 32.0,
    "manual_humidity_pct": 40.0,
    "manual_rainfall_mm": 0.0,
    "manual_evapotranspiration_mm": 6.0,
}


def test_model_service_loads_current_registry_latest_version():
    """ModelService(version="latest") — the exact same resolution every
    request path uses (see app/dependencies.py's get_model_service) — must
    load without raising and match registry.json's real "latest" pointer,
    not just "some" model."""
    service = ModelService(version="latest")

    assert service.version == get_latest_version()
    assert service.metrics  # real computed metrics, never empty for a pipeline-trained version
    assert service.pipeline is not None


def test_prediction_bounds_sanity_across_district_crop_grid(client):
    """20 (district, crop) combinations spread across the full 107-district
    roster, all 5 crops — every real model prediction must land in a
    physically sane range (never negative, never wildly beyond what the
    training target distribution could produce) and the response must be
    internally consistent (weather echoed back, a real model_version)."""
    district_names = list(DISTRICTS)  # DISTRICTS is a dict keyed by district name
    grid = []
    step = max(1, len(district_names) // 20)
    for i in range(20):
        district = district_names[(i * step) % len(district_names)]
        crop = CROPS[i % len(CROPS)]
        grid.append((district, crop))

    assert len(grid) == 20

    for district, crop in grid:
        response = client.post(
            "/api/v1/predict",
            json={
                "district": district,
                "crop_type": crop,
                "soil_moisture_pct": 25.0,
                "canal_flow_cusecs": 300.0,
                "use_live_weather": False,
                **VALID_MANUAL_WEATHER,
            },
        )

        assert response.status_code == 200, f"{district}/{crop}: {response.text}"
        body = response.json()
        recommendation = body["irrigation_recommendation_mm"]
        # Physical sanity, not a tight statistical bound — see
        # docs/DATA_VALIDATION.md for the training target's real range.
        # A flood override can legitimately force this to exactly 0.0.
        assert 0.0 <= recommendation <= 100.0, f"{district}/{crop}: {recommendation}"
        assert body["weather_used"]["source"] == "manual"
        if body["source"] == "model_prediction":
            assert body["model_version"] == get_latest_version()
