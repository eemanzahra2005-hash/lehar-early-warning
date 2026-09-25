"""Shared FastAPI dependencies (e.g. injected into routes via Depends())."""

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends

from app.config import Settings, get_settings
from app.db import get_db
from app.metrics import model_info
from app.services.alerts.engine import AlertEngine
from app.services.assistant import AssistantService
from app.services.drift import DriftService
from app.services.explain import ExplainService
from app.services.flood import FloodDischargeClient, FloodService
from app.services.flood_forecast import FloodForecastService
from app.services.llm import LLMService
from app.services.map_overview import MapOverviewService
from app.services.ml_model import ModelService
from app.services.performance import PerformanceService
from app.services.risk import RiskService
from app.services.weather import WeatherService

if TYPE_CHECKING:  # pragma: no cover - typing only
    # LEHAR Phase 1: MlflowRegistryService is deliberately NOT imported at
    # module level. This module is imported by every router, so anything
    # imported here is paid for by the API process on a 512MB host whether
    # or not a request ever uses it — and MLflow is the single heaviest
    # dependency in this project. The real import happens inside
    # get_mlflow_registry_service() below, i.e. only on the promote/rollback
    # path that actually needs it. See backend/tests/test_no_heavy_imports.py,
    # which enforces that a served request never pulls `mlflow` into
    # sys.modules.
    from app.services.mlflow_registry import MlflowRegistryService

__all__ = [
    "Settings",
    "get_settings",
    "get_db",
    "get_model_service",
    "set_model_service",
    "reload_model_service",
    "get_weather_service",
    "get_map_overview_service",
    "get_flood_discharge_client",
    "get_flood_service",
    "get_flood_forecast_service",
    "get_explain_service",
    "get_drift_service",
    "get_risk_service",
    "get_llm_service",
    "get_assistant_service",
    "get_mlflow_registry_service",
    "get_performance_service",
    "get_alert_engine",
    "get_telegram_bot",
    "get_email_channel",
]

# Module-global singleton holder (NOT @lru_cache) — Phase 7's promote/
# rollback API needs to atomically REPLACE this with a freshly-loaded
# ModelService instance (see reload_model_service below), which an
# argument-less lru_cache has no supported way to do without calling the
# function itself. Every other singleton in this module has no such
# hot-reload requirement and stays on the simpler @lru_cache pattern.
_model_service: ModelService | None = None


def get_model_service() -> ModelService:
    """Singleton: the trained pipeline is loaded from disk once per process
    (or once per reload_model_service() call — see below)."""
    global _model_service
    if _model_service is None:
        set_model_service(ModelService())
    return _model_service


def set_model_service(instance: ModelService) -> None:
    """Test-only hook (see backend/tests/test_models.py) to seed the
    singleton directly, e.g. pointing it at a temporary registry.

    Also the single choke point for the model_info gauge (Phase 10,
    app/metrics.py) — updated here rather than in ModelService.__init__ so
    it reflects whichever instance actually became the served singleton,
    covering both initial load (this function, called from
    get_model_service above) and promote/rollback (reload_model_service
    below). clear() first so a superseded version's label combination
    doesn't linger in /metrics as a stale, still-exposed series."""
    global _model_service
    _model_service = instance
    model_info.clear()
    model_info.labels(version=instance.version).set(1)


def reload_model_service(model_root: Path | None = None) -> ModelService:
    """Phase 7: called after a successful promote/rollback so every service
    built on top of ModelService reflects the newly-promoted version
    immediately, in-process, with no server restart.

    A NEW ModelService instance is constructed (rather than mutating the old
    one in place) so downstream lru_cache singletons keyed by ModelService
    identity (_explain_service_for, _map_overview_service_for,
    _assistant_service_for) correctly treat this as a cache miss and rebuild
    against the new model on their next call — including a fresh SHAP
    TreeExplainer, eagerly rebuilt here (not lazily on the next request) so
    the Explainability page reflects the new version right away, mirroring
    app/main.py's startup warm-up.

    Always resolves "latest" fresh from registry.json at `model_root`
    (regardless of a pinned MODEL_VERSION setting) — that's the whole point
    of promote/rollback: to actually change what's being served.
    """
    current = get_model_service()
    resolved_root = model_root if model_root is not None else current.model_root
    fresh = ModelService(model_root=resolved_root, version="latest")
    set_model_service(fresh)
    get_explain_service(fresh)
    return fresh


@lru_cache
def get_weather_service() -> WeatherService:
    """Singleton: reused across requests so its in-memory TTL cache is shared."""
    return WeatherService()


@lru_cache
def _map_overview_service_for(weather_service: WeatherService, model_service: ModelService) -> MapOverviewService:
    """Cached per (weather_service, model_service) identity, so tests that
    override get_weather_service via app.dependency_overrides transparently
    get a fresh MapOverviewService instead of reusing production's cache."""
    settings = get_settings()
    return MapOverviewService(weather_service, model_service, ttl_seconds=settings.map_overview_ttl_seconds)


def get_map_overview_service(
    weather_service: WeatherService = Depends(get_weather_service),
    model_service: ModelService = Depends(get_model_service),
) -> MapOverviewService:
    """FastAPI Depends default params (rather than a direct function call)
    so app.dependency_overrides on get_weather_service/get_model_service
    still applies to the whole dependency tree — see conftest.py."""
    return _map_overview_service_for(weather_service, model_service)


@lru_cache
def get_flood_discharge_client() -> FloodDischargeClient:
    """Singleton: real HTTP client for the Open-Meteo Flood API. Tests
    override this dependency with a fake to stay fully offline."""
    return FloodDischargeClient()


@lru_cache
def _flood_service_for(discharge_client: FloodDischargeClient, weather_service: WeatherService) -> FloodService:
    """Cached per (discharge_client, weather_service) identity — same
    rationale as _map_overview_service_for above."""
    settings = get_settings()
    return FloodService(discharge_client, weather_service, ttl_seconds=settings.flood_cache_ttl_seconds)


def get_flood_service(
    discharge_client: FloodDischargeClient = Depends(get_flood_discharge_client),
    weather_service: WeatherService = Depends(get_weather_service),
) -> FloodService:
    """FastAPI Depends default params so app.dependency_overrides on
    get_flood_discharge_client/get_weather_service still applies — see
    conftest.py and tests/test_flood.py."""
    return _flood_service_for(discharge_client, weather_service)


@lru_cache
def _flood_forecast_service_for(
    discharge_client: FloodDischargeClient, weather_service: WeatherService
) -> FloodForecastService:
    """Cached per (discharge_client, weather_service) identity — same
    rationale as _flood_service_for above. Caching also means the ONNX
    session, once built, is reused for every request instead of being
    rebuilt per call (LEHAR Phase 2.5)."""
    return FloodForecastService(discharge_client, weather_service)


def get_flood_forecast_service(
    discharge_client: FloodDischargeClient = Depends(get_flood_discharge_client),
    weather_service: WeatherService = Depends(get_weather_service),
) -> FloodForecastService:
    """LEHAR Phase 2.5's flood lead-time forecaster. FastAPI Depends default
    params so app.dependency_overrides on the discharge client / weather
    service still applies to the whole dependency tree, exactly as for
    get_flood_service — which is what keeps the offline test suite offline."""
    return _flood_forecast_service_for(discharge_client, weather_service)


@lru_cache
def _explain_service_for(model_service: ModelService) -> ExplainService:
    """Cached per model_service identity — the SHAP TreeExplainer is built
    ONCE (see ExplainService.__init__) and reused for every request."""
    return ExplainService(model_service)


def get_explain_service(model_service: ModelService = Depends(get_model_service)) -> ExplainService:
    """FastAPI Depends default param so app.dependency_overrides on
    get_model_service still applies to the whole dependency tree."""
    return _explain_service_for(model_service)


@lru_cache
def _drift_service_for(model_service: ModelService) -> DriftService:
    """Cached per model_service identity — same rationale as
    _explain_service_for above: a promote/rollback constructs a brand-new
    ModelService instance (see reload_model_service), which naturally
    invalidates this cache so the drift baseline (reference_distribution.json,
    read fresh from model_service.version/model_root on every compute())
    reflects the newly-promoted version's own baseline, not a stale one."""
    return DriftService(model_service)


def get_drift_service(model_service: ModelService = Depends(get_model_service)) -> DriftService:
    """FastAPI Depends default param so app.dependency_overrides on
    get_model_service still applies to the whole dependency tree."""
    return _drift_service_for(model_service)


@lru_cache
def get_risk_service() -> RiskService:
    """Singleton: purely a function of Settings' RISK_W_* weights, no
    external I/O, so a single shared instance is fine."""
    return RiskService()


@lru_cache
def get_mlflow_registry_service() -> "MlflowRegistryService":
    """Singleton: purely a function of Settings' MLFLOW_TRACKING_URI, no
    persistent connection to hold open. Tests override this dependency with
    a fake to stay fully offline (see conftest.py / test_models.py).

    The import is local (LEHAR Phase 1) so neither this module's import nor
    any other endpoint drags the MLflow client into a memory-constrained
    API process — only an actual promote/rollback call does. Note that
    app/services/mlflow_registry.py in turn imports `mlflow` itself lazily,
    inside set_champion_alias(), so even this path only pays for MLflow
    when a reachable tracking server is there to talk to."""
    from app.services.mlflow_registry import MlflowRegistryService

    return MlflowRegistryService()


@lru_cache
def get_performance_service() -> PerformanceService:
    """Singleton: stateless, no external I/O or config of its own — every
    call reads fresh from the request-scoped DB session it's given."""
    return PerformanceService()


@lru_cache
def _alert_engine_for(
    flood_service: FloodService,
    weather_service: WeatherService,
    model_service: ModelService,
    drift_service: DriftService,
    flood_forecast_service: FloodForecastService,
) -> AlertEngine:
    """Cached per (flood, weather, model, drift, flood forecast) identity —
    same rationale as _map_overview_service_for above, so a test overriding
    any one of those transparently gets a fresh engine, and a
    promote/rollback (which builds a new ModelService) rebuilds the engine
    against the new model."""
    return AlertEngine(
        flood_service=flood_service,
        weather_service=weather_service,
        model_service=model_service,
        drift_service=drift_service,
        flood_forecast_service=flood_forecast_service,
    )


def get_alert_engine(
    flood_service: FloodService = Depends(get_flood_service),
    weather_service: WeatherService = Depends(get_weather_service),
    model_service: ModelService = Depends(get_model_service),
    drift_service: DriftService = Depends(get_drift_service),
    flood_forecast_service: FloodForecastService = Depends(get_flood_forecast_service),
) -> AlertEngine:
    """LEHAR Phase 2's alert engine. FastAPI Depends default params so
    app.dependency_overrides on any underlying service still applies to the
    whole dependency tree — the offline test suite overrides the flood and
    weather services exactly as it does for /predict and the map."""
    return _alert_engine_for(
        flood_service, weather_service, model_service, drift_service, flood_forecast_service
    )


@lru_cache
def get_telegram_bot():
    """LEHAR Phase 3: the Telegram bot behind POST
    /api/v1/alerts/telegram/webhook. A singleton over Settings' TELEGRAM_*
    values; tests override it with a bot whose channel talks to an
    httpx.MockTransport. Imported lazily so a process that never receives a
    webhook call never builds it."""
    from app.services.alerts.channels.telegram import TelegramBot, TelegramChannel

    return TelegramBot(TelegramChannel())


@lru_cache
def get_email_channel():
    """LEHAR Phase 3: the Brevo email channel behind the double opt-in
    endpoints. Same singleton/override pattern as get_telegram_bot."""
    from app.services.alerts.channels.email import EmailChannel

    return EmailChannel()


@lru_cache
def get_llm_service() -> LLMService:
    """Singleton: purely a function of Settings' LLM_* config, no persistent
    connection to hold open. Tests override this dependency with a fake to
    stay fully offline (see conftest.py / test_assistant.py)."""
    return LLMService()


@lru_cache
def _assistant_service_for(
    weather_service: WeatherService,
    model_service: ModelService,
    risk_service: RiskService,
    flood_service: FloodService,
    explain_service: ExplainService,
) -> AssistantService:
    """Cached per (weather_service, model_service, risk_service, flood_service,
    explain_service) identity — same rationale as _map_overview_service_for
    above, so app.dependency_overrides on any of those still applies."""
    return AssistantService(weather_service, model_service, risk_service, flood_service, explain_service)


def get_assistant_service(
    weather_service: WeatherService = Depends(get_weather_service),
    model_service: ModelService = Depends(get_model_service),
    risk_service: RiskService = Depends(get_risk_service),
    flood_service: FloodService = Depends(get_flood_service),
    explain_service: ExplainService = Depends(get_explain_service),
) -> AssistantService:
    """FastAPI Depends default params so app.dependency_overrides on any of
    the underlying services still applies to the whole dependency tree."""
    return _assistant_service_for(weather_service, model_service, risk_service, flood_service, explain_service)
