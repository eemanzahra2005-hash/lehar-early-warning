# Fixtures are imported by name from sibling test modules (the pytest way to
# share them without a conftest); taking them as parameters reads as F811.
# ruff: noqa: F811
"""LEHAR Phase 4: alert operations — the extended /alerts/stats, the public
/alerts/health-summary banner, the new Prometheus metrics, the Grafana alert
panels, and the guarantee docs/SCHEDULER.md relies on (/health never touches
the database).

Offline throughout: the engine runs over test_alerts_api.py's three-district
set with its all-HIGH fake flood service; nothing reaches the network.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import event

import app.metrics as metrics_module
from app.db import Alert, AlertDelivery, AlertSubscription, get_engine, get_session_factory
from app.services.alerts.levels import DISCLAIMER_EN, DISCLAIMER_UR
from app.services.alerts.rules import TYPE_FLOOD
from app.services.alerts.summary import (
    HealthSummaryCache,
    health_summary_cache,
    latency_summary,
    percentile_nearest_rank,
)

# Reuse the Phase 2 API test setup: importing the autouse fixtures by name
# activates them in this module too (run token, OPS file, 3 districts).
from tests.test_alerts_api import (  # noqa: F401
    RUN_TOKEN,
    TEST_DISTRICT_NAMES,
    _alert_run_token,
    _small_district_set,
    flooded,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD = PROJECT_ROOT / "monitoring" / "grafana" / "dashboards" / "lehar-overview.json"
RUN_HEADERS = {"X-Alert-Run-Token": RUN_TOKEN}


@pytest.fixture(autouse=True)
def _fresh_health_summary_cache():
    """The cache is process-wide; the database is wiped per test."""
    health_summary_cache.invalidate()
    yield
    health_summary_cache.invalidate()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def add_rows(*rows):
    session = get_session_factory()()
    try:
        session.add_all(rows)
        session.commit()
    finally:
        session.close()


def an_alert(level=3, status="active", district="Multan", key=None, type=TYPE_FLOOD) -> Alert:
    return Alert(
        district_code=district,
        type=type,
        level=level,
        title_en="t",
        title_ur="t",
        body_en="b",
        body_ur="b",
        payload={},
        status=status,
        dedupe_key=key or f"{district}|{type}|{level}|{status}",
        created_at=datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc),
    )


def suppressed_detail(type_: str, level: str, reason: str) -> float:
    return metrics_module.alerts_suppressed_detail_total.labels(type=type_, level=level, reason=reason)._value.get()


# --- percentile helpers -------------------------------------------------------------

def test_nearest_rank_p95_is_always_an_observed_value():
    values = list(range(1, 101))  # 1..100
    assert percentile_nearest_rank(values, 95) == 95
    assert percentile_nearest_rank([7], 95) == 7
    assert percentile_nearest_rank([10, 20], 95) == 20


def test_latency_summary_uses_the_textbook_median():
    summary = latency_summary([400, 100, 300, 200])
    assert summary == {"sample_size": 4, "median_ms": 250.0, "p95_ms": 400}


def test_percentile_of_nothing_is_refused_not_invented():
    with pytest.raises(ValueError):
        percentile_nearest_rank([], 95)


# --- GET /alerts/stats: the Phase 4 additions ------------------------------------------

def test_stats_breaks_raised_alerts_down_by_type_and_level(flooded, register_user):
    token = register_user(username="ops1")
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)

    body = flooded.get("/api/v1/alerts/stats", headers=auth(token)).json()

    assert body["raised_by_type_and_level"] == {TYPE_FLOOD: {"3": len(TEST_DISTRICT_NAMES)}}
    assert body["resolved_by_type_and_level"] == {}
    # The Phase 2 fields are unchanged alongside the new ones.
    assert body["by_level"]["3"] == len(TEST_DISTRICT_NAMES)
    assert body["disclaimer"] == DISCLAIMER_EN


def test_stats_counts_resolved_alerts_per_type_and_level(client, register_user):
    token = register_user(username="ops2")
    add_rows(
        an_alert(level=3, status="resolved", key="a"),
        an_alert(level=3, status="resolved", key="b", district="Sukkur"),
        an_alert(level=2, status="active", key="c"),
    )

    body = client.get("/api/v1/alerts/stats", headers=auth(token)).json()

    assert body["resolved_by_type_and_level"] == {TYPE_FLOOD: {"3": 2}}
    assert body["raised_by_type_and_level"] == {TYPE_FLOOD: {"3": 2, "2": 1}}


def test_stats_reports_suppressions_durably_and_broken_down(flooded, register_user):
    token = register_user(username="ops3")
    before = suppressed_detail(TYPE_FLOOD, "3", "duplicate")

    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)
    second = flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS).json()

    body = flooded.get("/api/v1/alerts/stats", headers=auth(token)).json()
    # Durable total: the sum of every alert_runs row's own count.
    assert body["suppressed_total"] == second["alerts_suppressed"] == len(TEST_DISTRICT_NAMES)
    # The breakdown comes from the in-process counter, and says so.
    assert body["suppressed_breakdown_scope"] == "since_process_start"
    assert suppressed_detail(TYPE_FLOOD, "3", "duplicate") - before == len(TEST_DISTRICT_NAMES)
    assert body["suppressed_by_type_and_level"][TYPE_FLOOD]["3"] >= len(TEST_DISTRICT_NAMES)


def test_stats_counts_deliveries_per_channel_and_status(flooded, register_user):
    token = register_user(username="ops4")
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)

    body = flooded.get("/api/v1/alerts/stats", headers=auth(token)).json()

    # No channel is configured in tests, so only in-app delivery happened.
    assert body["deliveries_by_channel"] == {"in_app": {"sent": len(TEST_DISTRICT_NAMES)}}
    assert body["delivery_latency"] == {}


def test_stats_reports_median_and_p95_delivery_latency_per_external_channel(client, register_user):
    token = register_user(username="ops5")
    alert = an_alert()
    add_rows(alert)
    session = get_session_factory()()
    try:
        alert_id = session.query(Alert.id).scalar()
        rows = [
            AlertDelivery(alert_id=alert_id, channel="telegram", status="sent", attempts=1, latency_ms=ms)
            for ms in (100, 200, 300, 400, 5000)
        ]
        rows += [
            AlertDelivery(alert_id=alert_id, channel="email", status="sent", attempts=1, latency_ms=900),
            # Failed sends and in-app rows never count toward latency.
            AlertDelivery(alert_id=alert_id, channel="email", status="failed", attempts=3, latency_ms=99999),
            AlertDelivery(alert_id=alert_id, channel="in_app", status="sent", attempts=1, latency_ms=1),
        ]
        session.add_all(rows)
        session.commit()
    finally:
        session.close()

    body = client.get("/api/v1/alerts/stats", headers=auth(token)).json()

    assert body["delivery_latency"] == {
        "email": {"sample_size": 1, "median_ms": 900.0, "p95_ms": 900},
        "telegram": {"sample_size": 5, "median_ms": 300.0, "p95_ms": 5000},
    }
    assert body["deliveries_by_channel"]["email"] == {"sent": 1, "failed": 1}


def test_stats_counts_only_verified_subscriptions_as_active(client, register_user):
    token = register_user(username="ops6")
    add_rows(
        AlertSubscription(channel="email", target="a@b.c", districts=["Multan"], min_level=2, verified=True),
        AlertSubscription(channel="email", target="d@e.f", districts=["Multan"], min_level=2, verified=False),
        AlertSubscription(channel="telegram", target="12345", districts=["Multan"], min_level=2, verified=True),
    )

    body = client.get("/api/v1/alerts/stats", headers=auth(token)).json()

    assert body["subscriptions"] == 3  # Phase 2 meaning: every row
    assert body["active_subscriptions"] == 2
    assert body["active_subscriptions_by_channel"] == {"email": 1, "telegram": 1}


def test_stats_last_run_carries_its_duration(flooded, register_user):
    token = register_user(username="ops7")
    run = flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS).json()
    assert run["duration_seconds"] is not None and run["duration_seconds"] >= 0

    body = flooded.get("/api/v1/alerts/stats", headers=auth(token)).json()
    assert body["last_run"]["run_id"] == run["run_id"]
    assert body["last_run"]["duration_seconds"] >= 0


def test_stats_on_an_empty_database_has_empty_breakdowns(client, register_user):
    token = register_user(username="ops8")
    body = client.get("/api/v1/alerts/stats", headers=auth(token)).json()

    assert body["raised_by_type_and_level"] == {}
    assert body["deliveries_by_channel"] == {}
    assert body["delivery_latency"] == {}
    assert body["suppressed_total"] == 0
    assert body["active_subscriptions"] == 0


def test_stats_still_requires_a_jwt(client):
    assert client.get("/api/v1/alerts/stats").status_code == 401


# --- GET /alerts/health-summary ----------------------------------------------------------

SUMMARY = "/api/v1/alerts/health-summary"


def test_health_summary_is_public_and_calm_on_a_fresh_database(client):
    response = client.get(SUMMARY)
    assert response.status_code == 200
    body = response.json()

    assert body["highest_level"] == 1
    assert body["highest_level_key"] == "L1"
    assert body["counts_by_level"] == {"1": len(TEST_DISTRICT_NAMES), "2": 0, "3": 0, "4": 0, "5": 0}
    assert body["total_districts"] == len(TEST_DISTRICT_NAMES)
    assert body["alerting_districts"] == 0
    assert body["disclaimer"] == DISCLAIMER_EN
    assert body["disclaimer_ur"] == DISCLAIMER_UR


def test_health_summary_reports_the_national_highest_level_and_counts(client):
    add_rows(
        an_alert(level=4, district="Multan", key="m"),
        an_alert(level=2, district="Sukkur", key="s"),
        # Not counted: acknowledged, and OPS.
        an_alert(level=5, district="Lahore", status="acknowledged", key="l"),
        an_alert(level=0, district="SYSTEM", type="OPS", key="ops"),
    )

    body = client.get(SUMMARY).json()

    assert body["highest_level"] == 4
    assert body["highest_level_color_hex"] == "#7B2FBF"
    assert body["counts_by_level"] == {"1": 1, "2": 1, "3": 0, "4": 1, "5": 0}
    assert body["alerting_districts"] == 2


def test_health_summary_agrees_with_the_active_map(flooded):
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)

    summary = flooded.get(SUMMARY).json()
    active = flooded.get("/api/v1/alerts/active").json()

    assert summary["highest_level"] == max(row["level"] for row in active["districts"])
    assert summary["alerting_districts"] == active["alerting_count"]
    assert summary["total_districts"] == active["count"]


def test_health_summary_is_cached_and_says_so(client):
    first = client.get(SUMMARY)
    add_rows(an_alert(level=3, key="late"))  # written behind the API's back
    second = client.get(SUMMARY)

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["highest_level"] == 1  # still the cached answer
    assert second.json()["cache_ttl_seconds"] == 60
    assert second.headers["cache-control"] == "public, max-age=60"


def test_health_summary_cache_runs_no_query_while_fresh(client):
    client.get(SUMMARY)
    statements = []

    def count(*_args, **_kwargs):
        statements.append(1)

    event.listen(get_engine(), "before_cursor_execute", count)
    try:
        assert client.get(SUMMARY).json()["cached"] is True
    finally:
        event.remove(get_engine(), "before_cursor_execute", count)
    assert statements == []


def test_an_alert_run_refreshes_the_health_summary_immediately(flooded):
    assert flooded.get(SUMMARY).json()["highest_level"] == 1

    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)

    body = flooded.get(SUMMARY).json()
    assert body["cached"] is False
    assert body["highest_level"] == 3


def test_acknowledging_an_alert_refreshes_the_health_summary(flooded):
    run = flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS).json()
    assert flooded.get(SUMMARY).json()["alerting_districts"] == len(TEST_DISTRICT_NAMES)

    flooded.post(f"/api/v1/alerts/{run['raised_alert_ids'][0]}/ack")

    assert flooded.get(SUMMARY).json()["alerting_districts"] == len(TEST_DISTRICT_NAMES) - 1


def test_the_cache_expires_after_its_ttl():
    now = [100.0]
    cache = HealthSummaryCache(clock=lambda: now[0])
    builds = []

    def build():
        builds.append(1)
        return {"n": len(builds)}

    assert cache.get(60, build) == ({"n": 1}, False)
    now[0] = 159.9
    assert cache.get(60, build) == ({"n": 1}, True)
    now[0] = 160.0
    assert cache.get(60, build) == ({"n": 2}, False)


# --- Prometheus: last-run gauges and the suppression breakdown --------------------------------

def test_a_run_sets_the_last_run_gauges(flooded):
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)
    text = flooded.get("/metrics").text

    assert re.search(r"^lehar_alert_last_run_timestamp_seconds [1-9]", text, re.MULTILINE)
    assert f'lehar_alert_last_run_outcomes{{outcome="raised"}} {float(len(TEST_DISTRICT_NAMES))}' in text
    assert 'lehar_alert_last_run_outcomes{outcome="districts_checked"}' in text


def test_the_original_suppressed_counter_keeps_its_unlabelled_series(flooded):
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)
    flooded.post("/api/v1/alerts/run", headers=RUN_HEADERS)
    text = flooded.get("/metrics").text

    assert re.search(r"^lehar_alerts_suppressed_total \d", text, re.MULTILINE)
    assert 'lehar_alerts_suppressed_detail_total{level="3",reason="duplicate",type="FLOOD"}' in text


# --- Grafana: the provisioned alert panels ---------------------------------------------------

def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _registered_metric_names() -> set[str]:
    from prometheus_client.metrics import MetricWrapperBase

    names = set()
    for value in vars(metrics_module).values():
        if isinstance(value, MetricWrapperBase):
            for family in value.describe():
                names.add(family.name)
    return names


def test_the_dashboard_has_the_four_alert_panels():
    titles = {panel["title"] for panel in _dashboard()["panels"]}
    assert {
        "Alerts raised by level",
        "Deliveries by channel / status",
        "Delivery latency p95",
        "Last alert run",
    } <= titles


def test_dashboard_panel_ids_are_unique_and_panels_do_not_overlap():
    panels = _dashboard()["panels"]
    ids = [panel["id"] for panel in panels]
    assert len(ids) == len(set(ids))

    cells = set()
    for panel in panels:
        grid = panel["gridPos"]
        for x in range(grid["x"], grid["x"] + grid["w"]):
            for y in range(grid["y"], grid["y"] + grid["h"]):
                assert (x, y) not in cells, f"panel {panel['id']} overlaps another at {(x, y)}"
                cells.add((x, y))
        assert grid["x"] + grid["w"] <= 24


def test_every_alert_panel_queries_a_metric_the_api_really_exports():
    """A panel over a metric name that does not exist just shows 'No data'
    forever — this catches a typo before Grafana does."""
    exported = _registered_metric_names()
    for panel in _dashboard()["panels"]:
        for target in panel.get("targets", []):
            for name in re.findall(r"\blehar_[a-z_]+", target["expr"]):
                base = re.sub(r"_(bucket|count|sum)$", "", name)
                base = re.sub(r"_total$", "", base)
                assert base in exported, f"panel {panel['title']!r} queries unknown metric {name}"


def test_the_alert_row_carries_the_research_disclaimer():
    rows = [panel for panel in _dashboard()["panels"] if panel["type"] == "row"]
    assert any("NDMA/PMD/PDMA official warnings are authoritative" in row["title"] for row in rows)


# --- /health stays DB-free (docs/SCHEDULER.md depends on it) -----------------------------------

def test_health_runs_zero_sql_statements(client):
    """An uptime pinger hits /health every 5 minutes. One query each would
    keep Neon's free compute awake around the clock."""
    statements = []

    def count(*_args, **_kwargs):
        statements.append(1)

    event.listen(get_engine(), "before_cursor_execute", count)
    try:
        assert client.get("/api/v1/health").status_code == 200
    finally:
        event.remove(get_engine(), "before_cursor_execute", count)
    assert statements == []


def test_render_blueprint_declares_the_run_token_as_a_secret():
    import yaml

    blueprint = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    [api] = [service for service in blueprint["services"] if service["name"] == "lehar-api"]
    env = {item["key"]: item for item in api["envVars"]}
    assert env["ALERT_RUN_TOKEN"].get("sync") is False
    assert "value" not in env["ALERT_RUN_TOKEN"]
