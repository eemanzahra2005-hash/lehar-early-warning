"""Tests for Phase 9's Alembic migration chain (backend/migrations/).

Runs entirely against a temp SQLite file, not the shared conftest.py test
DB — this proves the migration chain itself upgrades a genuinely fresh
database to head, independent of the app's own create_all() fallback.
The real Postgres path was verified manually end-to-end (docs/DATABASE.md);
this test intentionally avoids depending on a live Postgres server so the
suite stays fast and Docker-free per CLAUDE.md rule 2.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.config as config_module
from app.db import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_alembic_upgrades_a_fresh_sqlite_database_to_head(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_alembic_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(cfg, "head")

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            assert {
                "users",
                "fields",
                "prediction_logs",
                "actual_observations",
                "alembic_version",
            } <= tables

            # Every column the live SQLAlchemy models declare today —
            # including the Phase 6 risk_score/risk_band columns — must be
            # present after a fresh upgrade, not just the tables.
            for table_name, table in Base.metadata.tables.items():
                actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
                expected_columns = {c.name for c in table.columns}
                assert expected_columns <= actual_columns, f"{table_name} missing columns after migration"
        finally:
            engine.dispose()
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()
