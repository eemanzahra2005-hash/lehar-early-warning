"""Tests for the secure response headers (Phase 11, app/middleware.py's
SecureHeadersMiddleware) — asserted on both a JSON API route and the
static-frontend route, since the middleware wraps every response."""


def test_security_headers_present_on_api_response(client):
    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response.headers


def test_csp_header_allows_self_and_documented_third_parties(client):
    response = client.get("/api/v1/health")
    csp = response.headers["Content-Security-Policy"]

    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "https://tile.openstreetmap.org" in csp  # the only real third-party origin (Leaflet map tiles)
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_security_headers_present_on_static_frontend_response(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


def test_security_headers_present_on_error_response(client):
    """The middleware wraps the whole app, including error paths — a 404
    should still carry the same defensive headers."""
    response = client.get("/api/v1/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers
