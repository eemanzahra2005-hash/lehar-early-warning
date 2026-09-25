"""Tests for the uniform JSON error handling (see app/middleware.py)."""


def test_unknown_route_returns_clean_json_404(client):
    response = client.get("/api/v1/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert body["error"] == "http_error"
    assert body["status_code"] == 404
    assert "detail" in body
