"""SQLAlchemy engine/session setup and ORM models.

SQLite is the zero-setup default (DB_PATH); PostgreSQL (Phase 9) is opted
into via the DATABASE_URL env var — see resolve_database_url() and
docs/DATABASE.md. The engine and session factory are created lazily and
cached at module level, so DATABASE_URL/DB_PATH only need to be set once
before the first call (tests override DB_PATH in conftest.py before
importing the app).
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def resolve_db_path() -> Path:
    """DB_PATH setting, resolved against the project root if relative."""
    raw = get_settings().db_path
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_database_url() -> str:
    """Full SQLAlchemy connection URL.

    DATABASE_URL (env) wins when set — e.g. a Postgres URL for Phase 9's
    docker-compose "db" service. Empty (the default) builds the same SQLite
    URL every earlier phase used, from DB_PATH — so an unconfigured checkout
    keeps working with zero setup."""
    configured = get_settings().database_url.strip()
    if configured:
        return _normalize_postgres_scheme(configured)
    return f"sqlite:///{resolve_db_path()}"


def _normalize_postgres_scheme(url: str) -> str:
    """Rewrite a bare "postgres://" or "postgresql://" URL to
    "postgresql+psycopg://" (Phase 13) — the convention most hosting
    platforms hand you (e.g. Render's DATABASE_URL, see render.yaml) uses
    the bare scheme, but this app needs the "+psycopg" driver suffix so
    SQLAlchemy picks psycopg v3, the driver actually installed (psycopg2 has
    no prebuilt wheel here — see docs/DATABASE.md). Any other scheme
    (including an already-correct "postgresql+psycopg://", or "sqlite://"
    for tests) passes through unchanged."""
    for bare_prefix in ("postgresql://", "postgres://"):
        if url.startswith(bare_prefix):
            return "postgresql+psycopg://" + url[len(bare_prefix):]
    return url


def is_sqlite_url(url: str | URL) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    fields: Mapped[list["Field"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    crop_type: Mapped[str] = mapped_column(String(32), nullable=False)
    default_soil_moisture_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_canal_flow_cusecs: Mapped[float | None] = mapped_column(Float, nullable=True)
    # LEHAR Phase 2: this field's own IRRIGATION_DUE trigger, in mm. None
    # (the default, and the value every row created before Phase 2 has)
    # means "use ALERT_IRRIGATION_THRESHOLD_MM" — see
    # app/services/alerts/rules.py's evaluate_irrigation_due.
    irrigation_threshold_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="fields")


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), nullable=True, index=True)
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    crop_type: Mapped[str] = mapped_column(String(32), nullable=False)
    soil_moisture_pct: Mapped[float] = mapped_column(Float, nullable=False)
    canal_flow_cusecs: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    rainfall_mm: Mapped[float] = mapped_column(Float, nullable=False)
    evapotranspiration_mm: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_mm: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Phase 6: Farm Risk Score at prediction time (see app/services/risk.py).
    # Nullable because rows logged before Phase 6 have neither.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    # Phase 10: at most one real recorded outcome per prediction (see
    # ActualObservation below) — None until the user records one.
    actual: Mapped["ActualObservation | None"] = relationship(
        back_populates="prediction_log", uselist=False, cascade="all, delete-orphan"
    )


class ActualObservation(Base):
    """Phase 10: a real-world irrigation outcome the user recorded against
    one of their own past predictions (POST /api/v1/history/{id}/actual) —
    the honest-performance-tracking building block for
    GET /api/v1/monitoring/performance. One-to-one with prediction_logs
    (unique constraint) so a prediction can only ever be recorded once —
    the router 409s on a second attempt rather than silently overwriting."""

    __tablename__ = "actual_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_log_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_logs.id"), nullable=False, unique=True, index=True
    )
    actual_irrigation_mm: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    prediction_log: Mapped["PredictionLog"] = relationship(back_populates="actual")

    prediction_log: Mapped["PredictionLog"] = relationship()


# --- LEHAR Phase 2: the alert engine's four tables -------------------------
#
# JSON columns use SQLAlchemy's dialect-neutral JSON type, which maps to
# SQLite's JSON1 text storage and to Postgres JSON — so the same models run
# on the local SQLite default and on Neon (CLAUDE.md rules 5 and 11).
# See app/services/alerts/ and docs/ALERT_LEVELS.md.


class Alert(Base):
    """One raised alert. Immutable once created except for `status` and
    `resolved_at` — a level change produces a NEW row (escalation), never an
    edit, so the history of what a farmer was actually told is auditable
    (CLAUDE.md rule 10)."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A district name from ml/districts.py, or the literal "SYSTEM" for
    # OPS alerts, which are about the platform rather than a place.
    district_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # FLOOD | HEAVY_RAIN | HEAT_STRESS | IRRIGATION_DUE | OPS | ALL_CLEAR
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # An alerts/levels.py level number: 0 (OPS) or 1-5.
    level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_ur: Mapped[str] = mapped_column(String(200), nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    body_ur: Mapped[str] = mapped_column(Text, nullable=False)
    # {"values": ..., "thresholds": ..., "source_timestamps": ..., "reason": ...}
    # — everything needed to re-derive this alert's level years later.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # active | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    # district + type + level + day (see alerts/engine.py's dedupe_key_for).
    # UNIQUE: the database itself is the dedupe guarantee, not just the
    # engine's query — a concurrent second run cannot duplicate an alert.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class AlertSubscription(Base):
    """Who receives which district's alerts, on which channel, from which
    level up. Phase 2 writes alert_deliveries rows against these; Phase 3
    adds the transports and the verification flow that sets `verified`."""

    __tablename__ = "alert_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # telegram | email
    # A Telegram chat id or an email address.
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    # List of district names; empty/null means every district.
    districts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="en")  # en | ur
    # False until the subscriber confirms — an unverified target is never
    # messaged (see alerts/channels.py's DeliveryDispatcher.dispatch).
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    deliveries: Mapped[list["AlertDelivery"]] = relationship(back_populates="subscription")


class AlertDelivery(Base):
    """One delivery attempt of one alert on one channel. Written for every
    attempt including skips, so "why didn't I get this?" always has an
    answer in the data."""

    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    # Null for in-app delivery, which belongs to the alert rather than to a
    # subscriber.
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_subscriptions.id"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # sent | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    alert: Mapped["Alert"] = relationship(back_populates="deliveries")
    subscription: Mapped["AlertSubscription | None"] = relationship(back_populates="deliveries")


class AlertRun(Base):
    """One evaluation pass over every district. Recorded for EVERY run,
    including runs that raised nothing — "the engine ran and found nothing"
    and "the engine never ran" must be distinguishable."""

    __tablename__ = "alert_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    districts_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_raised: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # cron | manual


_engine = None
_session_factory = None


def _build_engine(url: str | URL):
    """Construct a (not-yet-connected) Engine for the given URL. Split out
    from get_engine() so tests can build a throwaway engine for dialect/
    driver assertions without touching the cached global singleton below."""
    url = make_url(url)
    connect_args: dict = {}
    # SQLite-only: needed because a request-scoped session may be used
    # from a different thread than the one that created the connection
    # (FastAPI's threadpool for sync endpoints); Postgres has no such
    # restriction so this must not be passed to psycopg.
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine(resolve_database_url())
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _session_factory


def _ensure_prediction_log_risk_columns() -> None:
    """Phase 6 adds risk_score/risk_band to prediction_logs. create_all()
    only creates missing TABLES, not missing COLUMNS on a table that already
    exists (e.g. a real backend/data/app.db from Phases 1-5.5) — so this
    idempotent SQLite ALTER TABLE fills the gap. SQLite-only (uses PRAGMA
    table_info); the Postgres path never runs this — Alembic's initial
    migration (backend/migrations/) already creates these columns, see
    docs/DATABASE.md."""
    engine = get_engine()
    with engine.begin() as connection:
        existing_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(prediction_logs)")}
        if not existing_columns:
            return  # table doesn't exist yet — create_all() will create it with the columns already in place
        if "risk_score" not in existing_columns:
            connection.exec_driver_sql("ALTER TABLE prediction_logs ADD COLUMN risk_score FLOAT")
        if "risk_band" not in existing_columns:
            connection.exec_driver_sql("ALTER TABLE prediction_logs ADD COLUMN risk_band VARCHAR(16)")


def _ensure_field_alert_columns() -> None:
    """LEHAR Phase 2 adds fields.irrigation_threshold_mm. Same reason as
    _ensure_prediction_log_risk_columns above: create_all() creates missing
    TABLES, never missing COLUMNS on an existing one, so a real
    backend/data/app.db from an earlier phase needs this idempotent
    SQLite ALTER. Postgres gets the column from the Alembic migration."""
    engine = get_engine()
    with engine.begin() as connection:
        existing_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(fields)")}
        if not existing_columns:
            return  # table doesn't exist yet — create_all() builds it with the column already there
        if "irrigation_threshold_mm" not in existing_columns:
            connection.exec_driver_sql("ALTER TABLE fields ADD COLUMN irrigation_threshold_mm FLOAT")


def init_db() -> None:
    """SQLite dev/test fallback: create all tables that don't already exist,
    then apply any pending additive column migrations. Called on app
    startup.

    Postgres is intentionally NOT handled here — when DATABASE_URL points at
    Postgres, Alembic migrations (backend/migrations/, `alembic upgrade
    head`) are the sole source of truth for schema. Running create_all()
    against Postgres too would let the app silently create tables Alembic
    doesn't know about, so this is a no-op there; see docs/DATABASE.md."""
    engine = get_engine()
    if not is_sqlite_url(engine.url):
        return
    Base.metadata.create_all(bind=engine)
    _ensure_prediction_log_risk_columns()
    _ensure_field_alert_columns()


def get_db() -> Session:
    """FastAPI dependency yielding a request-scoped DB session."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
