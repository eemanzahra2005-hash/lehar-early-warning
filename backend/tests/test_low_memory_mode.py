"""LOW_MEMORY_MODE (Phase 13, e.g. Render's free tier — see render.yaml,
docs/DEPLOY_RENDER.md): the app's lifespan should skip the eager SHAP
explainer warm-up when enabled, building it lazily on first use instead.
"""

import asyncio
from unittest.mock import patch

import app.config as config_module
from app.main import app as fastapi_app
from app.main import lifespan


def _drive_lifespan():
    async def _run():
        async with lifespan(fastapi_app):
            pass

    asyncio.run(_run())


def test_lifespan_skips_eager_shap_warmup_when_low_memory_mode(monkeypatch):
    monkeypatch.setenv("LOW_MEMORY_MODE", "true")
    config_module.get_settings.cache_clear()
    try:
        with patch("app.main.get_explain_service") as mock_get_explain:
            _drive_lifespan()
            mock_get_explain.assert_not_called()
    finally:
        monkeypatch.delenv("LOW_MEMORY_MODE", raising=False)
        config_module.get_settings.cache_clear()


def test_lifespan_builds_shap_eagerly_by_default(monkeypatch):
    """Default (LOW_MEMORY_MODE unset/false) behavior is unchanged from
    pre-Phase-13: the explainer is still built during startup, not lazily."""
    monkeypatch.delenv("LOW_MEMORY_MODE", raising=False)
    config_module.get_settings.cache_clear()
    try:
        with patch("app.main.get_explain_service") as mock_get_explain:
            _drive_lifespan()
            mock_get_explain.assert_called_once()
    finally:
        config_module.get_settings.cache_clear()
