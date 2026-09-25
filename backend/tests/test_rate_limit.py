"""Dedicated rate-limit test (Phase 11).

Rate limiting is disabled for the rest of the suite (see conftest.py's
autouse `_disable_rate_limiting` fixture) — this is the one test that
re-enables it and asserts a real 429, then resets it back off so it never
leaks into any other test."""

from app.config import get_settings
from app.rate_limit import limiter


def test_auth_rate_limit_returns_429_after_exceeding_limit(client):
    limit = get_settings().rate_limit_auth_per_minute
    limiter.enabled = True
    try:
        last_response = None
        for _ in range(limit + 1):
            last_response = client.post(
                "/api/v1/auth/login",
                json={"username": "nonexistent-rl-test-user", "password": "whatever1"},
            )
        assert last_response.status_code == 429, last_response.text
        body = last_response.json()
        assert body["error"] == "rate_limit_exceeded"
        assert body["status_code"] == 429
    finally:
        limiter.enabled = False


def test_predict_rate_limit_returns_429_after_exceeding_limit(client):
    limit = get_settings().rate_limit_predict_per_minute
    limiter.enabled = True
    try:
        payload = {
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 30.0,
            "canal_flow_cusecs": 350.0,
            "use_live_weather": True,
        }
        last_response = None
        for _ in range(limit + 1):
            last_response = client.post("/api/v1/predict", json=payload)
        assert last_response.status_code == 429, last_response.text
    finally:
        limiter.enabled = False


def test_rate_limiting_is_disabled_by_default_in_tests(client):
    """Sanity check on the disable mechanism itself: hammering an endpoint
    well past its configured limit succeeds every time when the autouse
    fixture has left the limiter disabled (the state every other test in
    this suite runs under)."""
    limit = get_settings().rate_limit_auth_per_minute
    for _ in range(limit + 3):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nonexistent-rl-test-user-2", "password": "whatever1"},
        )
        assert response.status_code == 401  # invalid credentials, never 429
