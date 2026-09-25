"""Request-logging middleware, secure response headers, and JSON error handlers."""

import logging
import time

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.request")

# Phase 11: conservative CSP allowing only what this app actually serves.
# Every font (Inter/Space Grotesk/IBM Plex Mono) is vendored locally under
# frontend/vendor/fonts/ (CLAUDE.md rule 7 — no CDN at runtime, verified by
# grepping frontend/ for fonts.googleapis.com/fonts.gstatic.com: zero hits),
# so font-src/style-src stay same-origin — no Google Fonts host is needed
# despite the name "Google Fonts" (the *files*, not the CDN, are in use).
# The one genuine third-party origin is OSM's raster map tile server
# (Leaflet, Phase 5's Map page — frontend/js/views/map.js's tileLayer() call
# uses exactly this host, no {s} subdomain). 'unsafe-inline' on style-src is
# needed because Chart.js and Leaflet both set element `style` attributes
# directly in JS (canvas sizing, marker/tile positioning) — there is no
# inline <script> anywhere (frontend/index.html's former inline theme-init
# snippet was externalized to js/theme-init.js specifically so script-src
# can stay 'self' with no 'unsafe-inline'/nonce needed). Verified against
# every page with the browser console showing zero CSP violations — see
# docs/SECURITY.md.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data: https://tile.openstreetmap.org; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status code, and duration for every request.

    Skips /metrics (Phase 10): Prometheus scrapes it every 15s, and an INFO
    line per scrape would drown out real application traffic in the logs
    without adding any information Prometheus itself doesn't already have.
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        if request.url.path == "/metrics":
            return response

        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class SecureHeadersMiddleware(BaseHTTPMiddleware):
    """Adds a fixed set of defensive response headers (Phase 11) to every
    response — see docs/SECURITY.md for the rationale behind each one."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers that turn all errors into a clean, uniform JSON body.

    Shape: {"error": "<short code>", "detail": "<message>", "status_code": <int>}
    This keeps error responses predictable for the frontend and API consumers,
    instead of leaking FastAPI/Starlette's default HTML or inconsistent bodies.
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "detail": exc.detail,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "detail": exc.errors(),
                "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "rate_limit_exceeded",
                "detail": f"Too many requests — limit is {exc.detail}. Please slow down and try again shortly.",
                "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred.",
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            },
        )
