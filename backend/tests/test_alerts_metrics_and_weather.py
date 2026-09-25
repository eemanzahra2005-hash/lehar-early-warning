"""LEHAR Phase 2: the three Prometheus alert metrics, and the additive
WeatherService.fetch_daily_outlook() the HEAVY_RAIN / HEAT_STRESS rules
read from.

Both halves stay offline: the weather half fakes `requests.get` with a real
Open-Meteo-shaped payload, and the metrics half drives the engine with the
same fakes the engine tests use.
"""

from datetime import datetime, timezone

import pytest
import requests

from app.db import get_session_factory
from app.services import weather as weather_module
from app.services.alerts import engine as engine_module
from app.services.weather import WeatherService
from tests.test_alerts_engine import FakeFloodService, FakeWeatherService, flood_entry

T0 = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)


# --- WeatherService.fetch_daily_outlook ------------------------------------

class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


OUTLOOK_PAYLOAD = {
    "daily": {
        "time": ["2026-08-12", "2026-08-13", "2026-08-14"],
        "temperature_2m_max": [41.5, 46.0, 33.0],
        "precipitation_sum": [0.0, 12.5, 90.0],
    }
}


@pytest.fixture
def captured_params(monkeypatch):
    """Captures the query Open-Meteo would have been asked for."""
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        return FakeResponse(OUTLOOK_PAYLOAD)

    monkeypatch.setattr(weather_module.requests, "get", fake_get)
    return seen


def test_daily_outlook_asks_for_max_temperature_and_precipitation(captured_params):
    WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Multan", days=3)

    assert captured_params["params"]["daily"] == "temperature_2m_max,precipitation_sum"
    assert captured_params["params"]["forecast_days"] == 3


def test_daily_outlook_returns_one_entry_per_day_in_rule_shape(captured_params):
    outlook = WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Multan", days=3)

    assert outlook == [
        {"date": "2026-08-12", "temperature_max_c": 41.5, "rainfall_mm": 0.0},
        {"date": "2026-08-13", "temperature_max_c": 46.0, "rainfall_mm": 12.5},
        {"date": "2026-08-14", "temperature_max_c": 33.0, "rainfall_mm": 90.0},
    ]


def test_daily_outlook_rejects_an_unknown_district(captured_params):
    with pytest.raises(Exception) as exc_info:
        WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Atlantis")
    assert exc_info.value.status_code == 400


def test_daily_outlook_rejects_more_than_16_days(captured_params):
    with pytest.raises(Exception) as exc_info:
        WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Multan", days=20)
    assert exc_info.value.status_code == 400


def test_daily_outlook_turns_a_malformed_response_into_a_clean_502(monkeypatch):
    monkeypatch.setattr(
        weather_module.requests, "get", lambda url, params=None, timeout=None: FakeResponse({"nope": {}})
    )
    with pytest.raises(Exception) as exc_info:
        WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Multan")
    assert exc_info.value.status_code == 502


def test_daily_outlook_turns_a_network_failure_into_a_clean_502(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(weather_module.requests, "get", boom)
    with pytest.raises(Exception) as exc_info:
        WeatherService(cache_ttl_seconds=0).fetch_daily_outlook("Multan")
    assert exc_info.value.status_code == 502


def test_daily_outlook_has_its_own_cache_key_and_does_not_disturb_fetch_forecast(captured_params):
    """fetch_forecast() must keep returning temperature_2m_MEAN for the
    forecast page — the two methods share a cache dict but not a key."""
    service = WeatherService()
    service.fetch_daily_outlook("Multan", days=3)
    keys = set(service._cache)
    assert ("outlook", "Multan", 3) in keys
    assert ("forecast", "Multan", 3) not in keys


# --- Prometheus metrics ----------------------------------------------------

@pytest.fixture(autouse=True)
def _small_district_set(monkeypatch):
    from ml.districts import DISTRICTS as REAL_DISTRICTS

    monkeypatch.setattr(engine_module, "DISTRICTS", {"Multan": REAL_DISTRICTS["Multan"]})
    yield


@pytest.fixture(autouse=True)
def _isolated_ops_events(tmp_path, monkeypatch):
    import app.config as config_module

    monkeypatch.setenv("ALERT_OPS_EVENTS_PATH", str(tmp_path / "ops_events.jsonl"))
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def _metric_value(name, **labels):
    from prometheus_client import REGISTRY

    value = REGISTRY.get_sample_value(name, labels or None)
    return 0.0 if value is None else value


def _run_engine(db, flood):
    engine_module.AlertEngine(
        flood_service=flood, weather_service=FakeWeatherService(), model_service=None, drift_service=None
    ).run(db, now=T0)


def test_raised_and_suppressed_counters_move_on_a_real_run():
    session = get_session_factory()()
    try:
        before_raised = _metric_value("lehar_alerts_raised_total", type="FLOOD", level="3")
        before_suppressed = _metric_value("lehar_alerts_suppressed_total")

        flood = FakeFloodService({"Multan": flood_entry("HIGH", 70.0)})
        _run_engine(session, flood)
        _run_engine(session, flood)  # second run is a duplicate -> suppressed

        assert _metric_value("lehar_alerts_raised_total", type="FLOOD", level="3") == before_raised + 1
        assert _metric_value("lehar_alerts_suppressed_total") == before_suppressed + 1
    finally:
        session.close()


def test_run_duration_histogram_records_every_run():
    session = get_session_factory()()
    try:
        before = _metric_value("lehar_alert_run_duration_seconds_count")
        _run_engine(session, FakeFloodService())
        assert _metric_value("lehar_alert_run_duration_seconds_count") == before + 1
    finally:
        session.close()


def test_the_alert_metrics_are_exposed_on_the_metrics_endpoint(client):
    body = client.get("/metrics").text
    assert "lehar_alerts_raised_total" in body
    assert "lehar_alerts_suppressed_total" in body
    assert "lehar_alert_run_duration_seconds" in body
