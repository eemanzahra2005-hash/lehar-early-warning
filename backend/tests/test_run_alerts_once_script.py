"""LEHAR Phase 4: scripts/run_alerts_once.py.

The in-process mode runs the real engine over test_alerts_api.py's
three-district set against the test database; the remote mode posts to an
httpx.MockTransport. Neither touches the network.
"""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

import app.config as config_module
from app.db import AlertRun, get_session_factory
from app.services.alerts.levels import DISCLAIMER_EN
from tests.test_alerts_api import (  # noqa: F401
    RUN_TOKEN,
    TEST_DISTRICT_NAMES,
    FakeFloodServiceForApi,
    _alert_run_token,
    _small_district_set,
)

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_alerts_once.py"

SAMPLE_RUN = {
    "run_id": 7,
    "trigger": "cron",
    "started_at": "2026-08-12T06:00:00Z",
    "finished_at": "2026-08-12T06:00:12Z",
    "districts_checked": 107,
    "alerts_raised": 2,
    "alerts_suppressed": 3,
    "alerts_resolved": 1,
    "raised_alert_ids": [11, 12],
    "all_clear_alert_ids": [13],
    "suppressed": [
        {"district_code": "Multan", "type": "FLOOD", "level": 3, "reason": "duplicate"},
        {"district_code": "Sukkur", "type": "FLOOD", "level": 3, "reason": "duplicate"},
        {"district_code": "Lahore", "type": "HEAT_STRESS", "level": 2, "reason": "cooldown"},
    ],
    "disclaimer": DISCLAIMER_EN,
    "duration_seconds": 12.0,
}


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("run_alerts_once", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    config_module.get_settings.cache_clear()


def test_summary_is_short_readable_and_carries_the_disclaimer(script):
    text = script.format_summary(SAMPLE_RUN)

    assert "run #7 (cron)" in text
    assert "12.0 s" in text
    assert "Districts checked : 107" in text
    assert "Alerts raised     : 2" in text
    assert "Suppressed        : 3 (cooldown 1, duplicate 2)" in text
    assert "Resolved          : 1" in text
    assert "All-clears issued : 1" in text
    assert "New alert ids     : 11, 12" in text
    assert text.splitlines()[-1] == DISCLAIMER_EN
    assert len(text.splitlines()) <= 10


def test_in_process_run_uses_the_real_engine_and_records_the_run(script, monkeypatch, capsys):
    """build_engine() calls app.dependencies' providers directly (there is
    no FastAPI request to carry dependency_overrides), so the offline fakes
    are patched in at the provider level. The engine itself is real."""
    import app.dependencies as deps
    from tests.conftest import FakeFloodDischargeClient, FakeWeatherService

    weather, discharge = FakeWeatherService(), FakeFloodDischargeClient()
    monkeypatch.setattr(deps, "get_weather_service", lambda: weather)
    monkeypatch.setattr(deps, "get_flood_discharge_client", lambda: discharge)
    monkeypatch.setattr(deps, "get_flood_service", lambda *_args: FakeFloodServiceForApi())

    assert script.main(["--trigger", "cron"]) == 0

    out = capsys.readouterr().out
    assert f"Districts checked : {len(TEST_DISTRICT_NAMES)}" in out
    assert f"Alerts raised     : {len(TEST_DISTRICT_NAMES)}" in out
    assert DISCLAIMER_EN in out
    session = get_session_factory()()
    try:
        [run] = session.query(AlertRun).all()
        assert run.trigger == "cron"
        assert run.districts_checked == len(TEST_DISTRICT_NAMES)
    finally:
        session.close()


def test_json_flag_prints_the_full_run_response(script, monkeypatch, capsys):
    monkeypatch.setattr(script, "run_local", lambda trigger: dict(SAMPLE_RUN, trigger=trigger))

    assert script.main(["--json"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["trigger"] == "manual"
    assert printed["raised_alert_ids"] == [11, 12]


def test_remote_run_sends_exactly_what_the_scheduler_sends(script):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=SAMPLE_RUN)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    run = script.run_remote("https://lehar-api.example/", "s3cret", "cron", client=client)

    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "https://lehar-api.example/api/v1/alerts/run?trigger=cron"
    assert request.headers["X-Alert-Run-Token"] == "s3cret"
    assert run["run_id"] == 7


def test_remote_run_reports_a_refused_token(script, monkeypatch, capsys):
    def refuse(*_args, **_kwargs):
        request = httpx.Request("POST", "https://lehar-api.example/api/v1/alerts/run")
        raise httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, text="bad token"))

    monkeypatch.setattr(script, "run_remote", refuse)

    assert script.main(["--url", "https://lehar-api.example", "--token", "wrong"]) == 1
    assert "HTTP 401" in capsys.readouterr().err


def test_remote_run_needs_a_token(script, monkeypatch, capsys):
    monkeypatch.setenv("ALERT_RUN_TOKEN", "")
    config_module.get_settings.cache_clear()

    assert script.main(["--url", "https://lehar-api.example"]) == 1
    assert "ALERT_RUN_TOKEN" in capsys.readouterr().err


def test_remote_run_defaults_to_the_configured_token(script, monkeypatch):
    used = {}

    def fake_remote(base_url, token, trigger, client=None):
        used.update(base_url=base_url, token=token, trigger=trigger)
        return SAMPLE_RUN

    monkeypatch.setattr(script, "run_remote", fake_remote)

    assert script.main(["--url", "http://localhost:8000"]) == 0
    assert used == {"base_url": "http://localhost:8000", "token": RUN_TOKEN, "trigger": "manual"}


def test_the_script_is_importable_without_side_effects(script):
    """Importing (as the tests do) must not start a run."""
    session = get_session_factory()()
    try:
        assert session.query(AlertRun).count() == 0
    finally:
        session.close()
    assert "run_alerts_once" not in sys.argv[0]
