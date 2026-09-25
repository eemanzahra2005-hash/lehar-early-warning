"""Tests that the vanilla frontend is served at / (see app/main.py)."""


def test_root_serves_frontend_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "LEHAR" in response.text


def test_api_routes_still_take_priority_over_static_mount(client):
    """The static mount is registered last, so /api/v1/* must never be shadowed."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
