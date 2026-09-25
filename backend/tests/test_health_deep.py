"""GET /api/v1/health/deep and the RSS reporting behind it (LEHAR Phase 1).

The split matters operationally, so it is asserted rather than assumed:
/health is what an uptime pinger and Render's own health check hit, so it
must never touch the database; /health/deep is the diagnostic that does.
"""

from unittest.mock import patch

from app.routers import health as health_router


def test_deep_health_reports_ok_with_database_and_model_checks(client):
    response = client.get("/api/v1/health/deep")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["model"]["status"] == "ok"
    # The model check reports which version it verified.
    assert body["checks"]["model"]["detail"] == body["model_version"]


def test_deep_health_reports_real_rss_in_mb(client):
    """rss_mb must be a real psutil measurement — a plausible positive
    number for a running Python process with sklearn loaded, not a
    placeholder (CLAUDE.md rule 4)."""
    body = client.get("/api/v1/health/deep").json()

    assert body["rss_mb"] is not None, "psutil is a pinned dependency; RSS should be measurable here"
    assert isinstance(body["rss_mb"], (int, float))
    assert body["rss_mb"] > 0


def test_deep_health_reports_null_rss_rather_than_guessing(client):
    """When the measurement can't be taken, the field is null. It is never
    filled in with an estimate, and the endpoint still answers."""
    with patch("app.routers.health.current_rss_mb", return_value=None):
        response = client.get("/api/v1/health/deep")

    assert response.status_code == 200
    assert response.json()["rss_mb"] is None


def test_deep_health_degrades_instead_of_500_when_the_database_is_down(client):
    """A failing dependency must be REPORTED, not raised — a 500 here would
    tell an operator nothing about which check failed."""
    with patch.object(
        health_router, "_check_database",
        return_value=health_router.DeepHealthCheck(status="error", detail="OperationalError"),
    ):
        response = client.get("/api/v1/health/deep")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"


def test_plain_health_never_touches_the_database(client):
    """The contract that keeps /api/v1/health usable as an uptime ping: a
    slow or unreachable database must not be able to fail it (and so must
    not be able to trigger a restart loop on the deployed host)."""
    with patch("app.db.get_db", side_effect=AssertionError("/health must not open a DB session")):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_plain_health_response_has_no_rss_or_checks(client):
    """/health stays the cheap one — the diagnostic fields belong to
    /health/deep, which is deliberately the heavier endpoint."""
    body = client.get("/api/v1/health").json()

    assert "rss_mb" not in body
    assert "checks" not in body
