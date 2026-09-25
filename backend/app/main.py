"""FastAPI application factory and entry point.

Run locally with:
    .venv\\Scripts\\uvicorn app.main:app --reload --app-dir backend
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.db import init_db
from app.dependencies import get_explain_service, get_model_service
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware, SecureHeadersMiddleware, register_exception_handlers
from app.rate_limit import limiter
from app.routers import (
    alert_channels,
    alerts,
    assistant,
    auth,
    compare,
    explain,
    fields,
    flood,
    health,
    history,
    meta,
    models,
    monitoring,
    predict,
    report,
    weather,
)
from app.routers import (
    map as map_router,
)
from app.services.memory import log_startup_memory
from app.services.ml_model import ModelNotAvailableError

logger = logging.getLogger("app.startup")

# Project root (two levels above backend/app/), so this resolves correctly
# regardless of the working directory uvicorn is launched from.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if get_settings().low_memory_mode:
        # LOW_MEMORY_MODE (Phase 13, e.g. Render free tier): skip the eager
        # build below to keep boot-time memory down. ExplainService still
        # gets built the first time a request actually needs it (the
        # existing get_explain_service singleton — app/dependencies.py —
        # requires no other change), just later and lazily instead of here.
        logger.info("LOW_MEMORY_MODE enabled — skipping eager SHAP explainer warm-up.")
    else:
        try:
            # Eagerly build the SHAP explainer at startup (rather than lazily
            # on the first /predict request) so its one-time numba JIT
            # warm-up (~49s locally, never disk-cached across process runs —
            # see ExplainService._warm_up's docstring) happens here, not
            # while a user is waiting on their first prediction.
            logger.info("Warming up SHAP explainer (one-time JIT compilation, may take up to a minute)...")
            get_explain_service(get_model_service())
            logger.info("SHAP explainer ready.")
        except ModelNotAvailableError:
            logger.warning("No trained model available — skipping explainer warm-up.")

    if get_settings().log_memory:
        # LEHAR Phase 1: one real RSS reading, taken at the END of startup —
        # after init_db() and after whichever explainer branch above ran — so
        # it reports what the process genuinely costs once it is ready to
        # serve, in EITHER profile. (Logging it earlier would under-report
        # the local profile by the whole eager SHAP warm-up.) On a 512MB host
        # this is the single most useful line in the deploy log: the floor
        # every request then builds on. See docs/MEMORY.md.
        log_startup_memory()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        description=(
            "LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk. "
            "Early-warning and irrigation decision support for Pakistan's "
            "districts, with a full local MLOps lifecycle. "
            "All data used by this platform is SYNTHETIC research data."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecureHeadersMiddleware)

    # Phase 11: per-client-IP rate limiting on auth/predict/assistant routes
    # (see app/rate_limit.py, the @limiter.limit(...) decorators on those
    # routers, and register_exception_handlers' RateLimitExceeded handler
    # for the clean 429 JSON body).
    app.state.limiter = limiter

    register_exception_handlers(app)

    app.include_router(health.router, prefix=settings.api_v1_prefix)
    app.include_router(meta.router, prefix=settings.api_v1_prefix)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(weather.router, prefix=settings.api_v1_prefix)
    app.include_router(predict.router, prefix=settings.api_v1_prefix)
    app.include_router(models.router, prefix=settings.api_v1_prefix)
    app.include_router(fields.router, prefix=settings.api_v1_prefix)
    app.include_router(history.router, prefix=settings.api_v1_prefix)
    app.include_router(map_router.router, prefix=settings.api_v1_prefix)
    app.include_router(compare.router, prefix=settings.api_v1_prefix)
    app.include_router(flood.router, prefix=settings.api_v1_prefix)
    app.include_router(explain.router, prefix=settings.api_v1_prefix)
    app.include_router(assistant.router, prefix=settings.api_v1_prefix)
    app.include_router(monitoring.router, prefix=settings.api_v1_prefix)
    app.include_router(report.router, prefix=settings.api_v1_prefix)
    # LEHAR Phase 2: the alert engine's endpoints (see app/routers/alerts.py).
    app.include_router(alerts.router, prefix=settings.api_v1_prefix)
    # LEHAR Phase 3: Telegram webhook + email double opt-in
    # (see app/routers/alert_channels.py).
    app.include_router(alert_channels.router, prefix=settings.api_v1_prefix)

    # Phase 10: Prometheus metrics. instrument() adds automatic per-request
    # HTTP metrics (latency, in-progress, request/response size); expose()
    # registers GET /metrics (excluded from OpenAPI docs and from its own
    # instrumentation, so the scrape doesn't pollute its own histogram).
    # Custom app metrics (predictions_total, model_info, ...) live in
    # app/metrics.py and are incremented from the real code paths that
    # produce them — see docs/MONITORING.md.
    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )

    # Mounted last (and at "/") so /api/v1/* routes above always take priority
    # over the static file server. html=True serves frontend/index.html at "/"
    # and lets router.js handle unknown paths client-side via #/hash routes.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
