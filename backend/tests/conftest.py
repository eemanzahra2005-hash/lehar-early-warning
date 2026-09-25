"""Pytest fixtures shared across backend tests.

Sets DB_PATH to a temporary SQLite file and a fixed JWT_SECRET *before*
importing the app, so tests never touch the real backend/data/app.db.
The weather service dependency is overridden for every test (autouse) with
an in-memory fake, so this suite never makes a real HTTP call to Open-Meteo.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="smart_irrigation_test_"))
_TEST_DB_PATH = _TEST_DATA_DIR / "test_app.db"
os.environ["DB_PATH"] = str(_TEST_DB_PATH)

# LEHAR Phase 2: the OPS event log (app/services/alerts/ops_events.py) is a
# real file on disk, and POST /api/v1/models/rollback writes to it. Point it
# at the same throwaway directory as the test database so the suite never
# writes into the repo's backend/data/ — and so a rollback test can never
# leave a breadcrumb that makes a LATER alert-engine test raise a surprise
# OPS alert.
os.environ["ALERT_OPS_EVENTS_PATH"] = str(_TEST_DATA_DIR / "ops_events.jsonl")
os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production-use")

# Phase 11: force the real, documented defaults regardless of what a
# developer's local backend/.env happens to have (e.g. an older
# JWT_EXPIRE_MINUTES=10080 from before this phase) — same rationale as the
# LLM_CLOUD_API_KEY override below: tests must be deterministic and
# reflect the app's real intended config, not one machine's local file.
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["JWT_REFRESH_EXPIRE_MINUTES"] = "10080"

# os.environ takes priority over backend/.env in pydantic-settings, so this
# blanks out whatever LLM_CLOUD_API_KEY a developer's real local .env may
# have set (Phase 6.6 hybrid assistant) — tests must be deterministic and
# offline regardless of what's configured on the machine running them. Tests
# that specifically exercise cloud/hybrid behavior inject their own fake key
# via LLMService(cloud_api_key=...) dependency overrides instead.
os.environ["LLM_CLOUD_API_KEY"] = ""

# LEHAR Phase 2.5: same rationale as the two overrides above. Once a flood
# lead-time model is registered under backend/ml/flood_dl/model/, a developer
# whose local backend/.env sets FLOOD_DL_ENABLED=true would otherwise have
# the alert engine quietly start making real GloFAS/Open-Meteo calls during
# the suite. The tests that exercise the feature build their own
# FloodForecastService pointed at the committed ONNX fixture and enable it
# explicitly (see tests/test_flood_forecast_service.py), so the default here
# is the documented one: off.
os.environ["FLOOD_DL_ENABLED"] = "false"

# LEHAR Phase 3: same rationale again. A developer who has put a real
# TELEGRAM_BOT_TOKEN or BREVO_API_KEY in backend/.env must never have the
# suite message real people. Blank = every delivery channel disabled, which
# is also the documented default; the channel tests build their own
# channels with fake credentials over an httpx.MockTransport.
for _channel_env in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_USERNAME",
    "TELEGRAM_WEBHOOK_SECRET",
    "BREVO_API_KEY",
    "ALERT_FROM_EMAIL",
    "PUBLIC_BASE_URL",
):
    os.environ[_channel_env] = ""

import pytest
from fastapi.testclient import TestClient

from app.db import Base, get_engine
from app.dependencies import get_flood_discharge_client, get_weather_service
from app.main import app
from app.rate_limit import limiter
from app.services.soil import build_reading

# Phase 16: live soil moisture layers (m³/m³) served by FakeWeatherService —
# depth-weighted root zone (2*0.20 + 6*0.22 + 18*0.24) / 26 = 0.2323 -> 23.2%.
FAKE_SOIL_LAYERS = {
    "soil_moisture_1_to_3cm": 0.20,
    "soil_moisture_3_to_9cm": 0.22,
    "soil_moisture_9_to_27cm": 0.24,
}


class FakeWeatherService:
    """Deterministic stand-in for WeatherService — no real HTTP calls."""

    def fetch_soil_moisture(self, district: str) -> dict:
        # Built by the real pure helper, so only the network call is faked
        # and the reading's shape can never drift from WeatherService's.
        return build_reading(FAKE_SOIL_LAYERS, "2026-08-12T10:00")

    def fetch(self, district: str) -> dict:
        return {
            "temperature_c": 30.0,
            "humidity_pct": 45.0,
            "rainfall_mm": 2.0,
            "evapotranspiration_mm": 5.0,
        }

    def fetch_forecast(self, district: str, days: int = 7) -> list[dict]:
        return [
            {
                "date": f"2026-08-{12 + i:02d}",
                "temperature_c": 30.0 + i,
                "humidity_pct": 45.0,
                "rainfall_mm": 1.0,
                "evapotranspiration_mm": 5.0,
            }
            for i in range(days)
        ]

    def fetch_daily_outlook(self, district: str, days: int = 3) -> list[dict]:
        """LEHAR Phase 2: daily max temperature + precipitation, the two
        variables the HEAVY_RAIN/HEAT_STRESS rules read. The values are
        deliberately calm (32 C, 1 mm) — well under every alert threshold —
        so the default fake never raises a weather alert in tests that
        aren't about alerts. Alert tests inject their own outlook."""
        return [
            {"date": f"2026-08-{12 + i:02d}", "temperature_max_c": 32.0, "rainfall_mm": 1.0}
            for i in range(days)
        ]


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_database():
    """Wipe all tables before every test so tests never see each other's rows."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield


@pytest.fixture(autouse=True)
def _fake_weather_service():
    """Overrides the weather service dependency for every test."""
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService()
    yield
    app.dependency_overrides.pop(get_weather_service, None)


class FakeFloodDischargeClient:
    """Deterministic stand-in for FloodDischargeClient — no real HTTP calls.
    A flat, low 37-day discharge series (no anomaly) keeps every district's
    computed Flood Risk Index at a safely low score regardless of exposure or
    the real wall-clock month (see backend/tests/test_flood.py for the math),
    so this default never accidentally triggers the predict flood override in
    unrelated tests. Tests that specifically exercise flood behavior override
    get_flood_discharge_client themselves with a more targeted fake."""

    def fetch(self, lat: float, lon: float) -> dict:
        return {"dates": [f"d{i}" for i in range(37)], "values": [1.0] * 37}


@pytest.fixture(autouse=True)
def _fake_flood_discharge_client():
    """Overrides the flood discharge client dependency for every test."""
    app.dependency_overrides[get_flood_discharge_client] = lambda: FakeFloodDischargeClient()
    yield
    app.dependency_overrides.pop(get_flood_discharge_client, None)


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Rate limiting (Phase 11, app/rate_limit.py) is disabled for the whole
    suite by default — most tests fire many requests in a loop and aren't
    testing rate-limit behavior. `Limiter.enabled` is checked live on every
    request (not baked in at decoration time), so flipping it here/in a
    specific test works with no app restart. See
    backend/tests/test_rate_limit.py for the one dedicated test that flips
    it back on to assert a real 429."""
    limiter.enabled = False
    yield
    limiter.enabled = False


@pytest.fixture
def register_user(client: TestClient):
    """Factory fixture: register_user(username="alice", password="password123") -> access_token"""

    def _register(username: str = "alice", password: str = "password123", email: str | None = None) -> str:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password, "email": email},
        )
        assert response.status_code == 201, response.text
        return response.json()["access_token"]

    return _register
