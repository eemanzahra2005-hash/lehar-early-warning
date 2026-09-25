"""Tests for Phase 9's DATABASE_URL support in app/db.py.

Keeps the whole suite on SQLite (no live Postgres connection needed) per
CLAUDE.md rule 2 / PROGRESS.md's Phase 9 test plan: the postgresql:// case
only asserts the built Engine's dialect/driver, which SQLAlchemy's lazy
create_engine() computes without ever opening a socket.
"""

import app.config as config_module
from app.db import _build_engine, resolve_database_url, resolve_db_path


def test_resolve_database_url_defaults_to_sqlite_from_db_path():
    """No DATABASE_URL set -> same SQLite URL every pre-Phase-9 build used."""
    config_module.get_settings.cache_clear()
    try:
        assert resolve_database_url() == f"sqlite:///{resolve_db_path()}"
    finally:
        config_module.get_settings.cache_clear()


def test_resolve_database_url_honors_explicit_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/smart_irrigation")
    config_module.get_settings.cache_clear()
    try:
        assert resolve_database_url() == "postgresql+psycopg://user:pass@localhost:5432/smart_irrigation"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_resolve_database_url_normalizes_bare_postgres_scheme(monkeypatch):
    """Render's DATABASE_URL (and most hosting platforms') uses the bare
    "postgres://" scheme (Phase 13) — must be rewritten to
    "postgresql+psycopg://" so SQLAlchemy picks the actually-installed
    psycopg v3 driver rather than failing to find a default psycopg2."""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/smart_irrigation")
    config_module.get_settings.cache_clear()
    try:
        assert resolve_database_url() == "postgresql+psycopg://user:pass@localhost:5432/smart_irrigation"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_resolve_database_url_normalizes_bare_postgresql_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/smart_irrigation")
    config_module.get_settings.cache_clear()
    try:
        assert resolve_database_url() == "postgresql+psycopg://user:pass@localhost:5432/smart_irrigation"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_build_engine_for_sqlite_url(tmp_path):
    db_path = tmp_path / "engine_test.db"
    engine = _build_engine(f"sqlite:///{db_path}")
    try:
        assert engine.dialect.name == "sqlite"
        assert db_path.parent.exists()  # parent dir auto-created, matching pre-Phase-9 behaviour
    finally:
        engine.dispose()


def test_build_engine_for_postgresql_url_asserts_dialect_and_driver_only():
    """No live connection is made or needed here — create_engine() is lazy,
    so this proves the psycopg v3 driver (backend/requirements.txt) is wired
    up correctly without requiring a running Postgres server in CI."""
    engine = _build_engine("postgresql+psycopg://user:pass@localhost:5432/does_not_need_to_exist")
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()
