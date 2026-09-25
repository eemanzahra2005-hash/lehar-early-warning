"""Health check endpoints.

Two endpoints with deliberately different costs (LEHAR Phase 1):

  - GET /health — liveness only. Touches NOTHING external: no database
    query, no model load, no filesystem beyond registry.json. This is what
    an uptime pinger (cron-job.org, Render's own health check) hits every
    few minutes, so it must stay cheap enough to answer inside Render's
    fixed 5-second health-check timeout even on a cold, 512MB-constrained
    process.
  - GET /health/deep — readiness/diagnostics. Actually exercises the
    database and the model registry, and reports the process's real RSS.
    Slower and heavier by design; never wire an uptime pinger to it.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import DeepHealthCheck, DeepHealthResponse, HealthResponse
from app.services.memory import current_rss_mb
from ml.registry import DEFAULT_MODEL_ROOT, get_latest_version

logger = logging.getLogger("app.health")

router = APIRouter(tags=["health"])

# Bumped manually as the API evolves. Not tied to package versioning yet.
API_VERSION = "0.1.0"


def _resolve_model_version(settings: Settings) -> str | None:
    """Whichever model version will ACTUALLY be served: the registry's
    "latest" pointer when MODEL_VERSION is "latest" (the default), or the
    pinned MODEL_VERSION string itself otherwise (e.g. the compact
    deployment model — see render.yaml, docs/MEMORY.md). Mirrors
    ModelService's own resolution logic (app/services/ml_model.py) WITHOUT
    constructing a ModelService, so neither health endpoint pays for a
    joblib load — which under LOW_MEMORY_MODE has deliberately not happened
    yet at all."""
    return get_latest_version() if settings.model_version == "latest" else settings.model_version


@router.get("/health", response_model=HealthResponse)
def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness check used by the frontend, uptime pings and Render's own
    health check. Reads registry.json (a few KB of JSON) and nothing else —
    in particular it does NOT open a database connection, so a slow or
    unreachable database can never turn a live process into a failed health
    check and a restart loop. Use /health/deep to actually verify the
    database. model_version is None if no model has been trained yet. Must
    never raise.
    """
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=API_VERSION,
        environment=settings.environment,
        model_version=_resolve_model_version(settings),
    )


def _check_database(db: Session) -> DeepHealthCheck:
    """Real round-trip to the configured database (SQLite or Postgres).
    Any failure is reported as a check result, never raised — /health/deep
    reporting "the database is down" is more useful than /health/deep
    itself returning a 500."""
    try:
        db.execute(text("SELECT 1"))
        return DeepHealthCheck(status="ok")
    except Exception as exc:
        logger.warning("Deep health check: database query failed.", exc_info=True)
        return DeepHealthCheck(status="error", detail=type(exc).__name__)


def _check_model(version: str | None) -> DeepHealthCheck:
    """Verifies the resolved model version has a real model.joblib on disk.
    Deliberately a file-existence check rather than a joblib.load(): under
    LOW_MEMORY_MODE the model is loaded lazily on the first prediction, and
    a diagnostic endpoint must not be the thing that forces tens of MB of
    model into RSS on a 512MB host."""
    if version is None:
        return DeepHealthCheck(status="unavailable", detail="No model version registered yet.")
    if not (Path(DEFAULT_MODEL_ROOT) / version / "model.joblib").exists():
        return DeepHealthCheck(status="error", detail=f"model.joblib missing for version {version}")
    return DeepHealthCheck(status="ok", detail=version)


@router.get("/health/deep", response_model=DeepHealthResponse)
def get_deep_health(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> DeepHealthResponse:
    """Readiness/diagnostic check: database round-trip + model artifact
    presence + this process's current RSS in MB.

    status is "ok" only when every check passed, "degraded" otherwise —
    and the endpoint itself still returns 200 either way, so the body can
    be read and acted on rather than swallowed by an error handler.

    rss_mb is a real psutil measurement of this process, or null when it
    could not be taken (CLAUDE.md rule 4 — never an estimate). It is the
    number docs/MEMORY.md tracks against the 512MB deployment ceiling.
    """
    model_version = _resolve_model_version(settings)
    checks = {
        "database": _check_database(db),
        "model": _check_model(model_version),
    }
    overall = "ok" if all(check.status == "ok" for check in checks.values()) else "degraded"
    return DeepHealthResponse(
        status=overall,
        app=settings.app_name,
        version=API_VERSION,
        environment=settings.environment,
        model_version=model_version,
        rss_mb=current_rss_mb(),
        checks=checks,
    )
