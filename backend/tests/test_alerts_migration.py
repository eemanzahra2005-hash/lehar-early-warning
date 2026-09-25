"""LEHAR Phase 2: the alert tables' Alembic migration round-trip.

Runs against a throwaway SQLite file (not the shared conftest.py test DB),
so it proves the migration chain itself — not the app's create_all()
fallback — builds every alert table and column, and that downgrading undoes
exactly that and nothing else. The Postgres/Neon path uses the same
migration; keeping this test SQLite-only keeps the suite fast and
Docker-free (CLAUDE.md rule 2), matching test_alembic_migrations.py.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.config as config_module
from app.db import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent

PHASE_2_TABLES = {"alerts", "alert_subscriptions", "alert_deliveries", "alert_runs"}
# The revision immediately before the Phase 2 migration.
PRE_PHASE_2_REVISION = "c83b98abe752"
PHASE_2_REVISION = "b7f3a9c15e42"


def _alembic_config(db_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.get_settings.cache_clear()
    return Config(str(BACKEND_DIR / "alembic.ini"))


def test_upgrade_creates_every_alert_table_and_column(tmp_path, monkeypatch):
    db_path = tmp_path / "alerts_migration.db"
    try:
        command.upgrade(_alembic_config(db_path, monkeypatch), "head")

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            inspector = inspect(engine)
            assert PHASE_2_TABLES <= set(inspector.get_table_names())

            # Every column the live models declare must exist, for the four
            # new tables AND for the altered fields table.
            for table_name in PHASE_2_TABLES | {"fields"}:
                actual = {col["name"] for col in inspector.get_columns(table_name)}
                expected = {c.name for c in Base.metadata.tables[table_name].columns}
                assert expected <= actual, f"{table_name} missing columns after migration"

            # dedupe_key must be UNIQUE — the database, not just the engine,
            # is what guarantees an alert cannot be raised twice.
            dedupe_indexes = [
                index
                for index in inspector.get_indexes("alerts")
                if index["column_names"] == ["dedupe_key"]
            ]
            assert dedupe_indexes and dedupe_indexes[0]["unique"]
        finally:
            engine.dispose()
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_downgrade_then_upgrade_round_trips_cleanly(tmp_path, monkeypatch):
    db_path = tmp_path / "alerts_roundtrip.db"
    try:
        cfg = _alembic_config(db_path, monkeypatch)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, PRE_PHASE_2_REVISION)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            # The Phase 2 tables are gone; the inherited ones are untouched.
            assert not (PHASE_2_TABLES & tables)
            assert {"users", "fields", "prediction_logs", "actual_observations"} <= tables
            field_columns = {col["name"] for col in inspector.get_columns("fields")}
            assert "irrigation_threshold_mm" not in field_columns
            assert {"name", "district", "crop_type"} <= field_columns
        finally:
            engine.dispose()

        command.upgrade(cfg, "head")

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            inspector = inspect(engine)
            assert PHASE_2_TABLES <= set(inspector.get_table_names())
            assert "irrigation_threshold_mm" in {col["name"] for col in inspector.get_columns("fields")}
        finally:
            engine.dispose()
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_a_migrated_database_accepts_a_real_alert_row_and_rejects_a_duplicate(tmp_path, monkeypatch):
    """Round-trips actual data through the migrated schema — a migration
    that creates the right column names but the wrong types would pass a
    pure inspection test."""
    db_path = tmp_path / "alerts_data.db"
    try:
        command.upgrade(_alembic_config(db_path, monkeypatch), "head")

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            insert = text(
                "INSERT INTO alerts (district_code, type, level, title_en, title_ur, body_en, body_ur, "
                "payload, status, dedupe_key, created_at) "
                "VALUES ('Multan', 'FLOOD', 3, 't', 't', 'b', 'b', '{}', 'active', "
                "'Multan|FLOOD|3|2026-08-12', '2026-08-12 06:00:00')"
            )
            with engine.begin() as connection:
                connection.execute(insert)
                row = connection.execute(
                    text("SELECT district_code, level, status FROM alerts")
                ).one()
            assert row == ("Multan", 3, "active")

            duplicated = False
            try:
                with engine.begin() as connection:
                    connection.execute(insert)
            except Exception:
                duplicated = True
            assert duplicated, "dedupe_key UNIQUE constraint did not reject the duplicate"
        finally:
            engine.dispose()
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()


def test_the_phase_2_revision_sits_on_top_of_the_inherited_chain(tmp_path, monkeypatch):
    """Guards against a second head appearing in backend/migrations — a
    branched chain is the classic way `alembic upgrade head` stops applying
    everything (backend/docker-entrypoint.sh runs exactly that on deploy)."""
    from alembic.script import ScriptDirectory

    cfg = _alembic_config(tmp_path / "unused.db", monkeypatch)
    try:
        script = ScriptDirectory.from_config(cfg)
        assert list(script.get_heads()) == [PHASE_2_REVISION]
        assert script.get_revision(PHASE_2_REVISION).down_revision == PRE_PHASE_2_REVISION
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        config_module.get_settings.cache_clear()
