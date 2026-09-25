"""Tests for the additive risk_score/risk_band column migration in app/db.py
(_ensure_prediction_log_risk_columns), which exists so an existing SQLite
database from Phases 1-5.5 (before these columns existed) picks them up
without a manual migration step. Simulates a pre-Phase-6 table by dropping
the columns from the already-created table, then re-running the migration
function and confirming it adds them back — the exact code path a real
pre-Phase-6 backend/data/app.db would take on next startup.
"""

from app.db import _ensure_prediction_log_risk_columns, get_engine


def _column_names(engine) -> set[str]:
    with engine.begin() as connection:
        return {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(prediction_logs)")}


def test_migration_adds_missing_risk_columns_to_an_existing_table():
    engine = get_engine()
    assert {"risk_score", "risk_band"} <= _column_names(engine)  # conftest's create_all already added them

    # Simulate a pre-Phase-6 table that predates these columns.
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE prediction_logs DROP COLUMN risk_score")
        connection.exec_driver_sql("ALTER TABLE prediction_logs DROP COLUMN risk_band")
    assert not ({"risk_score", "risk_band"} & _column_names(engine))

    _ensure_prediction_log_risk_columns()

    assert {"risk_score", "risk_band"} <= _column_names(engine)


def test_migration_is_idempotent_when_columns_already_exist():
    engine = get_engine()
    assert {"risk_score", "risk_band"} <= _column_names(engine)

    _ensure_prediction_log_risk_columns()  # must not raise ("duplicate column" etc.)

    assert {"risk_score", "risk_band"} <= _column_names(engine)
