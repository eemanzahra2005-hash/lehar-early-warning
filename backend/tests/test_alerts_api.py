"""LEHAR Phase 2: the /api/v1/alerts endpoints.

Offline throughout — conftest.py's autouse fakes already stand in for
Open-Meteo's weather and flood APIs, and this module narrows the engine's
district sweep to three districts and injects its own flood service for the
run tests, so a POST /alerts/run in a test never touches the network.
"""

from datetime import datetime, timezone

import pytest

import app.config as config_module
from app.db import Alert, AlertSubscription, get_session_factory
from app.dependencies import get_flood_discharge_client, get_flood_service
from app.main import app
from app.services.alerts import engine as engine_module
from app.services.alerts.levels import DISCLAIMER_EN
from app.services.alerts.rules import TYPE_FLOOD, TYPE_HEAVY_RAIN

RUN_TOKEN = "test-alert-run-token"
T0 = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)

TEST_DISTRICT_NAMES = ("Multan", "Sukkur", "Lahore")


class FakeFloodServiceForApi:
    """Every district HIGH, so a single POST /alerts/run produces real,
    inspectable alerts without any network call."""

    def get_district(self, district):
        return {
            "district": district,
            "province": "Punjab",
            "status": "ok",
            "score": 70.0,
            "band": "HIGH",
            "components": {},
            "discharge": {
                "unit": "m3/s",
                "dates": [f"d{i}" for i in range(37)],
                "values": [5.0] * 30 + [10.0] * 7,
                "baseline_median": 5.0,
                "forecast_max": 10.0,
                "anomaly_ratio": 2.0,
            },
            "rain": {"dates": [], "values_mm": [], "cumulative_3day_mm": 0.0, "max_day_mm": 0.0},
        }


@pytest.fixture(autouse=True)
def _alert_run_token(monkeypatch, tmp_path):
    """Configure ALERT_RUN_TOKEN and isolate the OPS events file, then drop
    the settings cache so every test in this module sees the same config."""
    monkeypatch.setenv("ALERT_RUN_TOKEN", RUN_TOKEN)
    monkeypatch.setenv("ALERT_OPS_EVENTS_PATH", str(tmp_path / "ops_events.jsonl"))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _small_district_set(monkeypatch):
    from ml.districts import DISTRICTS as REAL_DISTRICTS

    monkeypatch.setattr(
        engine_module, "DISTRICTS", {name: REAL_DISTRICTS[name] for name in TEST_DISTRICT_NAMES}
    )
    yield


@pytest.fixture
def flooded(client):
    """Overrides the flood service so every district is HIGH for this test."""
    app.dependency_overrides[get_flood_service] = lambda: FakeFloodServiceForApi()
    yield client
    app.dependency_overrides.pop(get_flood_service, None)


def db_session():
    return get_session_factory()()


# --- POST /alerts/run: auth ------------------------------------------------

def test_run_rejects_a_request_with_no_token(client):
    assert client.post("/api/v1/alerts/run").status_code == 401


def test_run_rejects_a_wrong_token(client):
    response = client.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": "not-the-token"})
    assert response.status_code == 401
    assert "Invalid alert run token" in response.json()["detail"]


def test_run_accepts_the_configured_token(flooded):
    response = flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    assert response.status_code == 200, response.text
    assert response.json()["alerts_raised"] == len(TEST_DISTRICT_NAMES)


def test_run_refuses_entirely_when_no_token_is_configured(client, monkeypatch):
    """An unset ALERT_RUN_TOKEN must not mean "no auth required" — this
    endpoint drives the whole district sweep and writes farmer-facing
    alerts."""
    monkeypatch.setenv("ALERT_RUN_TOKEN", "")
    config_module.get_settings.cache_clear()

    response = client.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": "anything"})
    assert response.status_code == 503
    assert "ALERT_RUN_TOKEN" in response.json()["detail"]


def test_run_response_carries_the_disclaimer_and_the_run_bookkeeping(flooded):
    body = flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN}).json()

    assert body["disclaimer"] == DISCLAIMER_EN
    assert body["trigger"] == "manual"
    assert body["districts_checked"] == len(TEST_DISTRICT_NAMES)
    assert len(body["raised_alert_ids"]) == len(TEST_DISTRICT_NAMES)
    assert body["run_id"] is not None


def test_run_records_the_cron_trigger_when_asked(flooded):
    body = flooded.post(
        "/api/v1/alerts/run?trigger=cron", headers={"X-Alert-Run-Token": RUN_TOKEN}
    ).json()
    assert body["trigger"] == "cron"


def test_run_rejects_an_unknown_trigger(flooded):
    response = flooded.post(
        "/api/v1/alerts/run?trigger=whenever", headers={"X-Alert-Run-Token": RUN_TOKEN}
    )
    assert response.status_code == 422


def test_a_second_run_reports_its_suppressions_in_the_response(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    body = flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN}).json()

    assert body["alerts_raised"] == 0
    assert body["alerts_suppressed"] == len(TEST_DISTRICT_NAMES)
    assert {item["reason"] for item in body["suppressed"]} == {"duplicate"}


# --- GET /alerts -----------------------------------------------------------

def test_list_alerts_is_empty_on_a_fresh_database(client):
    body = client.get("/api/v1/alerts").json()
    assert body["count"] == 0
    assert body["alerts"] == []
    assert body["disclaimer"] == DISCLAIMER_EN


def test_list_alerts_returns_full_bilingual_alerts_after_a_run(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    body = flooded.get("/api/v1/alerts").json()

    assert body["count"] == len(TEST_DISTRICT_NAMES)
    alert = body["alerts"][0]
    assert alert["type"] == TYPE_FLOOD
    assert alert["level"] == 3
    assert alert["title_en"] and alert["title_ur"]
    assert alert["body_en"].endswith(DISCLAIMER_EN)
    assert alert["body_ur"].endswith(DISCLAIMER_EN)
    assert alert["payload"]["values"]["band"] == "HIGH"


def test_list_alerts_filters_by_district_level_type_and_status(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})

    assert flooded.get("/api/v1/alerts?district=Multan").json()["count"] == 1
    assert flooded.get("/api/v1/alerts?district=Atlantis").json()["count"] == 0
    assert flooded.get("/api/v1/alerts?level=3").json()["count"] == len(TEST_DISTRICT_NAMES)
    assert flooded.get("/api/v1/alerts?level=5").json()["count"] == 0
    assert flooded.get(f"/api/v1/alerts?type={TYPE_FLOOD}").json()["count"] == len(TEST_DISTRICT_NAMES)
    assert flooded.get(f"/api/v1/alerts?type={TYPE_HEAVY_RAIN}").json()["count"] == 0
    assert flooded.get("/api/v1/alerts?status=active").json()["count"] == len(TEST_DISTRICT_NAMES)
    assert flooded.get("/api/v1/alerts?status=resolved").json()["count"] == 0


def test_list_alerts_rejects_an_unknown_type_or_status(client):
    assert client.get("/api/v1/alerts?type=EARTHQUAKE").status_code == 400
    assert client.get("/api/v1/alerts?status=maybe").status_code == 400


def test_list_alerts_paginates(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    body = flooded.get("/api/v1/alerts?limit=1&offset=1").json()

    assert body["count"] == len(TEST_DISTRICT_NAMES)  # total, not page size
    assert len(body["alerts"]) == 1


# --- GET /alerts/active ----------------------------------------------------

def test_active_reports_every_district_at_the_calm_default_before_any_run(client):
    """Level 1 is COMPUTED, not stored — a fresh database still returns a
    complete, white map with nothing in the alerts table."""
    body = client.get("/api/v1/alerts/active").json()

    assert body["count"] == len(TEST_DISTRICT_NAMES)
    assert body["alerting_count"] == 0
    assert body["default_level"] == 1
    assert all(row["level"] == 1 for row in body["districts"])
    assert all(row["source"] == "default" for row in body["districts"])
    assert all(row["alert_id"] is None and row["type"] is None for row in body["districts"])
    assert body["disclaimer"] == DISCLAIMER_EN
    assert client.get("/api/v1/alerts").json()["count"] == 0


def test_active_reports_one_row_per_district_with_its_highest_level(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    body = flooded.get("/api/v1/alerts/active").json()

    assert body["count"] == len(TEST_DISTRICT_NAMES)
    assert body["alerting_count"] == len(TEST_DISTRICT_NAMES)
    assert {row["district"] for row in body["districts"]} == set(TEST_DISTRICT_NAMES)
    assert all(row["level"] == 3 for row in body["districts"])
    assert all(row["source"] == "alert" for row in body["districts"])
    assert all(row["title_en"] and row["title_ur"] for row in body["districts"])


def test_a_calm_sweep_raises_nothing_but_still_returns_a_full_active_map(client):
    """conftest.py's flood fake is a flat, low discharge series, so every
    district lands in the LOW band — which now writes no alert rows."""
    response = client.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})

    assert response.json()["alerts_raised"] == 0
    assert client.get("/api/v1/alerts").json()["count"] == 0

    active = client.get("/api/v1/alerts/active").json()
    assert active["count"] == len(TEST_DISTRICT_NAMES)
    assert active["alerting_count"] == 0
    assert all(row["level"] == 1 for row in active["districts"])


# --- GET /alerts/levels ----------------------------------------------------

def test_levels_serves_all_six_levels_with_colours_names_and_channels(client):
    body = client.get("/api/v1/alerts/levels").json()
    levels = {entry["number"]: entry for entry in body["levels"]}

    assert sorted(levels) == [0, 1, 2, 3, 4, 5]
    assert levels[0]["audience"] == "admin"
    assert levels[5]["name_en"] == "Emergency"
    assert all(entry["color_hex"].startswith("#") for entry in body["levels"])
    assert all(entry["name_ur"] for entry in body["levels"])
    assert levels[1]["channels"] == ["in_app"]
    assert set(levels[3]["channels"]) == {"in_app", "telegram", "email"}
    assert levels[4]["full_screen_takeover"] is True
    assert levels[2]["full_screen_takeover"] is False
    assert body["disclaimer"] == DISCLAIMER_EN
    assert "Japan" in body["note"]


def test_levels_needs_no_authentication(client):
    assert client.get("/api/v1/alerts/levels").status_code == 200


# --- POST /alerts/{id}/ack -------------------------------------------------

def test_ack_moves_an_active_alert_to_acknowledged(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    alert_id = flooded.get("/api/v1/alerts").json()["alerts"][0]["id"]

    body = flooded.post(f"/api/v1/alerts/{alert_id}/ack").json()
    assert body["status"] == "acknowledged"
    assert flooded.get("/api/v1/alerts?status=acknowledged").json()["count"] == 1


def test_ack_is_idempotent(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    alert_id = flooded.get("/api/v1/alerts").json()["alerts"][0]["id"]

    flooded.post(f"/api/v1/alerts/{alert_id}/ack")
    second = flooded.post(f"/api/v1/alerts/{alert_id}/ack")
    assert second.status_code == 200
    assert second.json()["status"] == "acknowledged"


def test_ack_drops_the_district_back_to_the_calm_default_on_the_active_map(flooded):
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    alert_id = flooded.get("/api/v1/alerts?district=Multan").json()["alerts"][0]["id"]

    flooded.post(f"/api/v1/alerts/{alert_id}/ack")

    active = flooded.get("/api/v1/alerts/active").json()
    multan = {row["district"]: row for row in active["districts"]}["Multan"]
    # Still on the map — every district always is — but back to white.
    assert multan["level"] == 1
    assert multan["source"] == "default"
    assert active["alerting_count"] == len(TEST_DISTRICT_NAMES) - 1


def test_ack_on_an_unknown_alert_is_a_404(client):
    assert client.post("/api/v1/alerts/999999/ack").status_code == 404


def test_ack_on_a_resolved_alert_is_a_409(client):
    session = db_session()
    try:
        session.add(
            Alert(
                district_code="Multan",
                type=TYPE_FLOOD,
                level=3,
                title_en="t",
                title_ur="t",
                body_en="b",
                body_ur="b",
                payload={},
                status="resolved",
                dedupe_key="Multan|FLOOD|3|2026-08-12",
                created_at=T0,
                resolved_at=T0,
            )
        )
        session.commit()
        alert_id = session.query(Alert).one().id
    finally:
        session.close()

    assert client.post(f"/api/v1/alerts/{alert_id}/ack").status_code == 409


# --- GET /alerts/stats -----------------------------------------------------

def test_stats_requires_a_jwt(client):
    assert client.get("/api/v1/alerts/stats").status_code == 401


def test_stats_reports_real_counts_after_a_run(flooded, register_user):
    token = register_user(username="admin1")
    flooded.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})

    body = flooded.get("/api/v1/alerts/stats", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["total_alerts"] == len(TEST_DISTRICT_NAMES)
    assert body["active_alerts"] == len(TEST_DISTRICT_NAMES)
    assert body["resolved_alerts"] == 0
    assert body["by_type"][TYPE_FLOOD] == len(TEST_DISTRICT_NAMES)
    assert body["by_level"]["3"] == len(TEST_DISTRICT_NAMES)
    assert body["deliveries_by_status"]["sent"] == len(TEST_DISTRICT_NAMES)
    assert body["total_runs"] == 1
    assert body["last_run"]["districts_checked"] == len(TEST_DISTRICT_NAMES)
    assert body["disclaimer"] == DISCLAIMER_EN


def test_stats_counts_subscriptions(flooded, register_user):
    token = register_user(username="admin2")
    session = db_session()
    try:
        session.add(
            AlertSubscription(
                channel="email", target="a@b.c", districts=["Multan"], min_level=2, language="ur", verified=True
            )
        )
        session.commit()
    finally:
        session.close()

    body = flooded.get("/api/v1/alerts/stats", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["subscriptions"] == 1


def test_stats_on_an_empty_database_reports_zeroes_not_an_error(client, register_user):
    token = register_user(username="admin3")
    body = client.get("/api/v1/alerts/stats", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["total_alerts"] == 0
    assert body["total_runs"] == 0
    assert body["last_run"] is None


# --- the alert engine stays offline ---------------------------------------

def test_a_run_makes_no_real_network_call(client):
    """conftest.py's autouse fakes cover weather and the flood discharge
    client, so the default engine path is already fully offline — this runs
    it end-to-end through the real FloodService to prove it."""
    app.dependency_overrides.pop(get_flood_service, None)
    response = client.post("/api/v1/alerts/run", headers={"X-Alert-Run-Token": RUN_TOKEN})
    assert response.status_code == 200
    assert get_flood_discharge_client in app.dependency_overrides
