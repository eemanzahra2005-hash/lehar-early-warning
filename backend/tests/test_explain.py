"""Tests for real per-prediction explainability (Phase 6):
app/services/explain.py's SHAP aggregation, POST /api/v1/predict's
explanation/confidence fields (including the never-break-on-failure
contract), and GET /api/v1/explain/global. Uses the real trained pipeline
from backend/ml/model/ — SHAP values themselves are never mocked, only the
explainer object is swapped out to prove failure tolerance.
"""

from app.dependencies import get_explain_service, get_model_service
from app.main import app
from app.services.explain import ExplainService
from ml.explain_utils import AGGREGATED_FEATURE_ORDER

VALID_MANUAL_WEATHER = {
    "manual_temperature_c": 38.0,
    "manual_humidity_pct": 22.0,
    "manual_rainfall_mm": 0.0,
    "manual_evapotranspiration_mm": 7.5,
}


# --- Aggregation -----------------------------------------------------------------

def test_explain_service_is_available_with_the_real_model():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    assert explain_service.available is True


def test_aggregation_returns_exactly_the_11_features():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    explanation = explain_service.explain(row)
    assert explanation is not None
    feature_names = {c["feature"] for c in explanation["contributions"]}
    assert feature_names == set(AGGREGATED_FEATURE_ORDER)
    assert len(explanation["contributions"]) == 11


def test_contributions_sum_to_prediction_minus_base_value():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    raw_prediction = model_service.predict_row(row)
    explanation = explain_service.explain(row)

    assert explanation is not None
    total_contribution = sum(c["contribution_mm"] for c in explanation["contributions"])
    reconstructed = explanation["base_value_mm"] + total_contribution
    assert abs(reconstructed - raw_prediction) < 0.5


def test_contributions_sorted_by_absolute_magnitude_descending():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    explanation = explain_service.explain(row)
    magnitudes = [abs(c["contribution_mm"]) for c in explanation["contributions"]]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_top_factors_are_nonempty_plain_english_sentences():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    explanation = explain_service.explain(row)
    assert 2 <= len(explanation["top_factors"]) <= 4
    for sentence in explanation["top_factors"]:
        assert isinstance(sentence, str)
        assert sentence.endswith(".")


def test_confidence_interval_brackets_are_ordered_and_reasonable():
    model_service = get_model_service()
    explain_service = ExplainService(model_service)
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    confidence = explain_service.confidence(row)
    assert confidence is not None
    assert confidence["tree_std_mm"] >= 0.0
    p10, p90 = confidence["interval_mm"]
    assert p10 <= p90


def test_explain_returns_none_when_internal_explainer_is_broken():
    """Belt-and-suspenders at the service layer: even if the TreeExplainer
    itself misbehaves after construction, explain() must swallow the error
    and return None rather than raising."""
    model_service = get_model_service()
    explain_service = ExplainService(model_service)

    class BoomExplainer:
        expected_value = 0.0

        def shap_values(self, X):
            raise RuntimeError("simulated SHAP failure")

    explain_service._explainer = BoomExplainer()
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    assert explain_service.explain(row) is None


def test_explain_service_unavailable_when_shap_cannot_be_built(monkeypatch):
    """Simulates the documented fallback path: if shap can't be imported /
    TreeExplainer can't be built, ExplainService.available is False and
    explain() always returns None, without raising."""
    model_service = get_model_service()

    class FakeModelService:
        pipeline = model_service.pipeline

    import app.services.explain as explain_module

    real_import = __import__

    def broken_import(name, *args, **kwargs):
        if name == "shap":
            raise ImportError("simulated: shap not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", broken_import)
    broken_service = explain_module.ExplainService(FakeModelService())
    monkeypatch.undo()

    assert broken_service.available is False
    row = model_service.build_feature_row(
        temperature_c=38.0,
        humidity_pct=22.0,
        rainfall_mm=0.0,
        evapotranspiration_mm=7.5,
        canal_flow_cusecs=150.0,
        soil_moisture_pct=18.0,
        district="Multan",
        crop_type="cotton",
    )
    assert broken_service.explain(row) is None
    # confidence() doesn't depend on the SHAP explainer, so it still works.
    assert broken_service.confidence(row) is not None


# --- POST /api/v1/predict ---------------------------------------------------------

def test_predict_response_includes_explanation_and_confidence(client):
    response = client.post(
        "/api/v1/predict",
        json={
            "district": "Multan",
            "crop_type": "cotton",
            "soil_moisture_pct": 18.0,
            "canal_flow_cusecs": 150.0,
            "use_live_weather": False,
            **VALID_MANUAL_WEATHER,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] is not None
    assert body["explanation"]["contributions"]
    assert body["explanation"]["top_factors"]
    assert body["confidence"] is not None
    assert "tree_std_mm" in body["confidence"]
    assert len(body["confidence"]["interval_mm"]) == 2


def test_predict_explanation_and_confidence_are_null_on_sensor_fault(client):
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
    assert body["explanation"] is None
    assert body["confidence"] is None


class BrokenExplainService:
    """Stand-in that always raises — proves POST /api/v1/predict stays 200
    and degrades to explanation=null/confidence=null even if the whole
    explain service misbehaves (defense in depth beyond ExplainService's
    own internal try/except)."""

    def explain(self, row):
        raise RuntimeError("simulated explain failure")

    def confidence(self, row):
        raise RuntimeError("simulated confidence failure")


def test_predict_stays_200_when_explainer_is_broken(client):
    app.dependency_overrides[get_explain_service] = lambda: BrokenExplainService()
    try:
        response = client.post(
            "/api/v1/predict",
            json={
                "district": "Multan",
                "crop_type": "cotton",
                "soil_moisture_pct": 18.0,
                "canal_flow_cusecs": 150.0,
                "use_live_weather": False,
                **VALID_MANUAL_WEATHER,
            },
        )
    finally:
        app.dependency_overrides.pop(get_explain_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation"] is None
    assert body["confidence"] is None
    assert body["irrigation_recommendation_mm"] >= 0
    assert body["risk"] is not None  # unrelated to explainability, must be unaffected


# --- GET /api/v1/explain/global -------------------------------------------------

def test_global_explain_returns_real_data_for_current_model(client):
    response = client.get("/api/v1/explain/global")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["sample_size"] == 500
    assert set(body["mean_abs_shap_mm"].keys()) == set(AGGREGATED_FEATURE_ORDER)
    assert all(v >= 0 for v in body["mean_abs_shap_mm"].values())


class ModelServiceWithoutGlobalShap:
    """Points at the real model's directory/version so /predict-adjacent
    behavior is unaffected, but pretends a different (nonexistent) version
    to exercise the available=false path."""

    def __init__(self, real_model_service):
        self.model_root = real_model_service.model_root
        self.version = "v-does-not-exist"


def test_global_explain_returns_available_false_when_file_missing(client):
    real_model_service = get_model_service()
    app.dependency_overrides[get_model_service] = lambda: ModelServiceWithoutGlobalShap(real_model_service)
    try:
        response = client.get("/api/v1/explain/global")
    finally:
        app.dependency_overrides.pop(get_model_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["mean_abs_shap_mm"] is None
