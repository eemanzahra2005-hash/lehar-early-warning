"""LEHAR Phase 1: the startup RSS log, and CORS for a split deployment.

Both exist because the API is moving from "same-origin app that serves its
own frontend" to "standalone JSON API inside a 512MB box, called by a
separate Next.js console".
"""

import logging
from unittest.mock import patch

import app.config as config_module
from app.config import Settings
from app.services.memory import current_rss_mb, log_startup_memory

# --- Startup memory log (LOG_MEMORY) ----------------------------------------


def test_current_rss_mb_returns_a_real_positive_measurement():
    rss = current_rss_mb()

    assert rss is not None, "psutil is a pinned dependency; RSS should be measurable here"
    assert rss > 0


def test_current_rss_mb_returns_none_when_psutil_is_unavailable():
    """CLAUDE.md rule 4: no measurement means null, never a stand-in
    number. Simulated with the exact failure a missing psutil produces."""
    with patch("builtins.__import__", side_effect=ImportError("No module named 'psutil'")):
        assert current_rss_mb() is None


def test_log_startup_memory_logs_the_real_value(caplog):
    with caplog.at_level(logging.INFO, logger="app.memory"):
        logged = log_startup_memory()

    assert logged is not None
    assert "Startup memory: RSS" in caplog.text
    # The number in the log line is the number returned — not a re-reading
    # taken at some other moment, and not rounded differently.
    assert f"{logged:.1f} MB" in caplog.text


def test_log_startup_memory_says_so_rather_than_logging_a_placeholder(caplog):
    with caplog.at_level(logging.WARNING, logger="app.memory"):
        with patch("app.services.memory.current_rss_mb", return_value=None):
            assert log_startup_memory() is None

    assert "could not be measured" in caplog.text


def test_lifespan_logs_startup_memory_only_when_log_memory_is_enabled(monkeypatch):
    """The flag has to actually gate the call: this line lands in a deploy
    log on every boot when enabled, and must be silent when not."""
    import asyncio

    from app.main import app as fastapi_app
    from app.main import lifespan

    def drive():
        async def _run():
            async with lifespan(fastapi_app):
                pass

        asyncio.run(_run())

    # Keep the run cheap and independent of the SHAP warm-up branch.
    monkeypatch.setenv("LOW_MEMORY_MODE", "true")
    try:
        for log_memory, should_log in (("true", True), ("false", False)):
            monkeypatch.setenv("LOG_MEMORY", log_memory)
            config_module.get_settings.cache_clear()
            with patch("app.main.log_startup_memory") as mock_log:
                drive()
                assert mock_log.called is should_log, f"LOG_MEMORY={log_memory}"
    finally:
        monkeypatch.delenv("LOG_MEMORY", raising=False)
        monkeypatch.delenv("LOW_MEMORY_MODE", raising=False)
        config_module.get_settings.cache_clear()


# --- CORS for the split deployment (FRONTEND_ORIGINS) -----------------------


def test_frontend_origins_defaults_include_the_console_dev_origin():
    """The Next.js console runs on :3000 in dev — it must work against a
    local API with no extra configuration."""
    origins = Settings().cors_origins_list

    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins


def test_frontend_origins_is_merged_with_cors_origins_not_replacing_it():
    """CLAUDE.md rule 1: adding the console's origin must not silently stop
    this repo's own same-origin frontend from being allowed."""
    settings = Settings(
        cors_origins="http://localhost:8000",
        frontend_origins="https://console.example.com",
    )

    assert settings.cors_origins_list == ["http://localhost:8000", "https://console.example.com"]


def test_cors_origins_list_parses_comma_separated_values_and_trims_whitespace():
    settings = Settings(
        cors_origins=" http://a.example.com , http://b.example.com ",
        frontend_origins="",
    )

    assert settings.cors_origins_list == ["http://a.example.com", "http://b.example.com"]


def test_cors_origins_list_deduplicates_while_preserving_order():
    """An origin named in both variables should be allowed once, not twice —
    Starlette matches on an exact list, so a duplicate is just noise."""
    settings = Settings(
        cors_origins="http://localhost:8000,http://localhost:3000",
        frontend_origins="http://localhost:3000,https://console.example.com",
    )

    assert settings.cors_origins_list == [
        "http://localhost:8000",
        "http://localhost:3000",
        "https://console.example.com",
    ]


def test_cross_origin_request_from_the_console_is_allowed(client, monkeypatch):
    """End-to-end through the real middleware: a browser request from the
    console's dev origin gets the header that lets the response through."""
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_from_the_console_succeeds(client):
    """The console's authenticated calls send `Authorization`, which makes
    them non-simple requests — so the OPTIONS preflight has to pass too."""
    response = client.options(
        "/api/v1/predict",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unlisted_origin_is_not_granted_cors_access(client):
    response = client.get("/api/v1/health", headers={"Origin": "https://not-allowed.example.com"})

    # The request itself still succeeds server-side; what matters is that no
    # allow-origin header is handed back, so a browser blocks the response.
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") is None
