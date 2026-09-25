"""Per-client-IP rate limiting (Phase 11) via slowapi (an in-memory sliding-
window limiter — a single-process store is fine for this local-first app;
see docs/SECURITY.md).

Limits are read live from Settings on every request (not baked in at import
time), so RATE_LIMIT_*_PER_MINUTE in .env takes effect without code changes.

Disabled automatically for the whole pytest suite (see conftest.py's
autouse `_disable_rate_limiting` fixture, which flips `limiter.enabled`)
except one dedicated test that re-enables it to assert a real 429
(test_rate_limit.py) — `Limiter.enabled` is checked live on every request,
so toggling it at runtime works with no app restart.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

limiter = Limiter(key_func=get_remote_address)


def auth_rate_limit() -> str:
    return f"{get_settings().rate_limit_auth_per_minute}/minute"


def predict_rate_limit() -> str:
    return f"{get_settings().rate_limit_predict_per_minute}/minute"


def assistant_rate_limit() -> str:
    return f"{get_settings().rate_limit_assistant_per_minute}/minute"
