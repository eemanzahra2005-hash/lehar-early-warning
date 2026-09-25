"""Tests for GET /api/v1/health."""


def test_health_returns_200_and_ok_status(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert "app" in body
    assert "version" in body
    assert "environment" in body
    # model_version must be present (string or null) and must never crash
    # the endpoint, even before any model has been trained.
    assert "model_version" in body
