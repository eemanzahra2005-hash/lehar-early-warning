"""Tests for Phase 10's Prometheus instrumentation: GET /metrics is
reachable and reflects real custom metrics incremented from real code
paths (app/metrics.py) — never fabricated."""


def test_metrics_endpoint_is_reachable(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    # prometheus_client's default exposition content type.
    assert "text/plain" in response.headers["content-type"]


def test_metrics_contains_predictions_total_after_a_predict_call(client, register_user):
    token = register_user(username="metricsuser")
    headers = {"Authorization": f"Bearer {token}"}

    predict_response = client.post(
        "/api/v1/predict",
        json={
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 300.0,
            "use_live_weather": True,
        },
        headers=headers,
    )
    assert predict_response.status_code == 200, predict_response.text

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert "predictions_total" in body
    assert 'district="Lahore"' in body


def test_metrics_contains_model_info_gauge(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "model_info" in response.text
