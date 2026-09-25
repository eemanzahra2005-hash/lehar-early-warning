"""Alert endpoints (LEHAR Phase 2) — all additive, nothing else changes.

    POST /api/v1/alerts/run        run the engine over every district
    GET  /api/v1/alerts            filterable alert list
    GET  /api/v1/alerts/active     per-district highest active level
    GET  /api/v1/alerts/levels     the level scheme (single source of truth)
    GET  /api/v1/alerts/stats      admin counters (JWT)
    GET  /api/v1/alerts/health-summary  national banner (public, cached)
    POST /api/v1/alerts/{id}/ack   acknowledge one alert

Auth model for this phase:
  - /run is machine-triggered (Phase 6's cron-job.org) and guarded by the
    X-Alert-Run-Token shared secret, not a JWT — a scheduler has no user
    account. With ALERT_RUN_TOKEN unset the endpoint refuses every call
    rather than running unauthenticated.
  - /stats is admin data, so it requires a JWT.
  - the read endpoints and /ack are open, like POST /api/v1/predict: a
    farmer must be able to see and dismiss a flood warning without an
    account. Phase 4 revisits this when subscriptions gain owners.

LEHAR Phase 4 extends /stats with per-type/level and per-channel
breakdowns and delivery latency, and adds /health-summary — both read-only
aggregations in app/services/alerts/summary.py.
"""

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.db import Alert, AlertDelivery, AlertRun, AlertSubscription, User, get_db
from app.dependencies import get_alert_engine
from app.schemas import (
    ActiveAlertsResponse,
    AlertHealthSummaryResponse,
    AlertLevelsResponse,
    AlertListResponse,
    AlertResponse,
    AlertRunResponse,
    AlertStatsResponse,
)
from app.services.alerts.engine import (
    CALM_LEVEL,
    SOURCE_ALERT,
    STATUS_ACKNOWLEDGED,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TRIGGER_CRON,
    TRIGGER_MANUAL,
    AlertEngine,
    AlertRunResult,
    highest_active_by_district,
)
from app.services.alerts.levels import DISCLAIMER_EN, all_levels
from app.services.alerts.rules import ALERT_TYPES
from app.services.alerts.summary import build_health_summary, health_summary_cache, operations_stats

logger = logging.getLogger("app.alerts")

router = APIRouter(prefix="/alerts", tags=["alerts"])

VALID_STATUSES = (STATUS_ACTIVE, STATUS_ACKNOWLEDGED, STATUS_RESOLVED)

LEVELS_NOTE = (
    "LEHAR's five farmer-facing levels are adapted from Japan's five-level disaster alert "
    "system, plus a grey admin-only OPS level (number 0) that is never shown to farmers. "
    "Every level, colour, name and action served here comes from "
    "app/services/alerts/levels.py — see docs/ALERT_LEVELS.md."
)


def _duration_seconds(started_at: datetime, finished_at: datetime | None) -> float | None:
    if finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds(), 3)


def _run_response(result: AlertRunResult) -> AlertRunResponse:
    return AlertRunResponse(
        run_id=result.run_id,
        trigger=result.trigger,
        started_at=result.started_at,
        finished_at=result.finished_at,
        districts_checked=result.districts_checked,
        alerts_raised=result.alerts_raised,
        alerts_suppressed=result.alerts_suppressed,
        alerts_resolved=result.alerts_resolved,
        raised_alert_ids=result.raised_alert_ids,
        all_clear_alert_ids=result.all_clear_alert_ids,
        suppressed=[
            {
                "district_code": item.district_code,
                "type": item.type,
                "level": item.level,
                "reason": item.reason,
            }
            for item in result.suppressed
        ],
        disclaimer=DISCLAIMER_EN,
        duration_seconds=_duration_seconds(result.started_at, result.finished_at),
    )


@router.post("/run", response_model=AlertRunResponse)
def run_alerts(
    trigger: str = Query(default=TRIGGER_MANUAL, pattern=f"^({TRIGGER_CRON}|{TRIGGER_MANUAL})$"),
    x_alert_run_token: str | None = Header(default=None, alias="X-Alert-Run-Token"),
    db: Session = Depends(get_db),
    engine: AlertEngine = Depends(get_alert_engine),
) -> AlertRunResponse:
    """Evaluate every district and raise/suppress/resolve accordingly.

    Guarded by the ALERT_RUN_TOKEN shared secret in the X-Alert-Run-Token
    header. An unset token means "not configured" and returns 503 — this
    endpoint drives 107 upstream fetches and writes farmer-facing alerts, so
    it must never be callable by an anonymous request."""
    expected = get_settings().alert_run_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alert runs are not configured: set ALERT_RUN_TOKEN.",
        )
    # Compared with hmac.compare_digest to keep the check constant-time, the
    # same standard applied to password verification in app/auth.py.
    if x_alert_run_token is None or not hmac.compare_digest(x_alert_run_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid alert run token.")

    result = engine.run(db, trigger=trigger)
    # The banner must show a new alert now, not up to a TTL later.
    health_summary_cache.invalidate()
    logger.info(
        "alert.run trigger=%s districts=%s raised=%s suppressed=%s resolved=%s",
        result.trigger,
        result.districts_checked,
        result.alerts_raised,
        result.alerts_suppressed,
        result.alerts_resolved,
    )
    return _run_response(result)


@router.get("", response_model=AlertListResponse)
def list_alerts(
    district: str | None = Query(default=None),
    level: int | None = Query(default=None, ge=0, le=5),
    type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AlertListResponse:
    """Newest first. Every filter is optional and they combine with AND.

    `district` is matched exactly against the stored district_code (a
    district name from ml/districts.py, or "SYSTEM" for OPS alerts) and is
    deliberately NOT validated against the district list — an OPS alert has
    no district, and a filter that matches nothing should return an empty
    list, not a 400."""
    if type is not None and type not in ALERT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown alert type: {type}")
    if status_filter is not None and status_filter not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown alert status: {status_filter}"
        )

    query = db.query(Alert)
    if district is not None:
        query = query.filter(Alert.district_code == district)
    if level is not None:
        query = query.filter(Alert.level == level)
    if type is not None:
        query = query.filter(Alert.type == type)
    if status_filter is not None:
        query = query.filter(Alert.status == status_filter)

    total = query.count()
    rows = query.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit).all()
    return AlertListResponse(
        count=total,
        alerts=[AlertResponse.model_validate(row) for row in rows],
        disclaimer=DISCLAIMER_EN,
    )


@router.get("/active", response_model=ActiveAlertsResponse)
def list_active_alerts(db: Session = Depends(get_db)) -> ActiveAlertsResponse:
    """EVERY district's current level — the shape the map choropleth and
    the dashboard banner need, with no gaps to fill in client-side.

    A district with an ACTIVE farmer-facing alert reports that alert's
    highest level (`source: "alert"`). A district with none reports the
    computed calm default, level 1 white (`source: "default"`) — nothing is
    stored for a calm district. Acknowledged and resolved alerts, ALL_CLEARs
    and OPS notices are all excluded."""
    districts = highest_active_by_district(db)
    return ActiveAlertsResponse(
        generated_at=datetime.now(timezone.utc),
        count=len(districts),
        alerting_count=sum(1 for row in districts if row["source"] == SOURCE_ALERT),
        default_level=CALM_LEVEL,
        districts=districts,
        disclaimer=DISCLAIMER_EN,
    )


@router.get("/levels", response_model=AlertLevelsResponse)
def get_alert_levels() -> AlertLevelsResponse:
    """The whole level scheme, served straight from
    app/services/alerts/levels.py so the console, the local frontend and
    the docs can never drift from what the engine actually uses."""
    return AlertLevelsResponse(levels=all_levels(), disclaimer=DISCLAIMER_EN, note=LEVELS_NOTE)


@router.get("/stats", response_model=AlertStatsResponse)
def get_alert_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AlertStatsResponse:
    """Admin counters for the console. Every number is a real COUNT(*) over
    the alert tables — nothing estimated (CLAUDE.md rule 4)."""
    by_status = dict(db.query(Alert.status, func.count(Alert.id)).group_by(Alert.status).all())
    by_type = dict(db.query(Alert.type, func.count(Alert.id)).group_by(Alert.type).all())
    by_level = {
        str(level): count
        for level, count in db.query(Alert.level, func.count(Alert.id)).group_by(Alert.level).all()
    }
    deliveries_by_status = dict(
        db.query(AlertDelivery.status, func.count(AlertDelivery.id)).group_by(AlertDelivery.status).all()
    )

    last_run_row = db.query(AlertRun).order_by(AlertRun.started_at.desc(), AlertRun.id.desc()).first()
    last_run = None
    if last_run_row is not None:
        last_run = AlertRunResponse(
            run_id=last_run_row.id,
            trigger=last_run_row.trigger,
            started_at=last_run_row.started_at,
            finished_at=last_run_row.finished_at or last_run_row.started_at,
            districts_checked=last_run_row.districts_checked,
            alerts_raised=last_run_row.alerts_raised,
            alerts_suppressed=last_run_row.alerts_suppressed,
            alerts_resolved=last_run_row.alerts_resolved,
            raised_alert_ids=[],
            all_clear_alert_ids=[],
            suppressed=[],
            disclaimer=DISCLAIMER_EN,
            duration_seconds=_duration_seconds(last_run_row.started_at, last_run_row.finished_at),
        )

    return AlertStatsResponse(
        total_alerts=sum(by_status.values()),
        active_alerts=by_status.get(STATUS_ACTIVE, 0),
        acknowledged_alerts=by_status.get(STATUS_ACKNOWLEDGED, 0),
        resolved_alerts=by_status.get(STATUS_RESOLVED, 0),
        by_level=by_level,
        by_type=by_type,
        by_status=by_status,
        deliveries_by_status=deliveries_by_status,
        subscriptions=db.query(func.count(AlertSubscription.id)).scalar() or 0,
        total_runs=db.query(func.count(AlertRun.id)).scalar() or 0,
        last_run=last_run,
        disclaimer=DISCLAIMER_EN,
        **operations_stats(db),
    )


@router.get("/health-summary", response_model=AlertHealthSummaryResponse)
def get_alert_health_summary(response: Response, db: Session = Depends(get_db)) -> AlertHealthSummaryResponse:
    """The public console banner: the national highest active level and how
    many districts sit at each level. No auth — it says nothing /alerts/active
    doesn't already say publicly.

    Cached for ALERT_HEALTH_SUMMARY_TTL_SECONDS (60 s): every console page
    load calls this, and on Neon's free tier every query keeps the database
    compute awake. A run or an acknowledgement clears the cache, so the TTL
    only ever delays "nothing changed". Not an uptime-ping target — point
    pingers at GET /api/v1/health, which never touches the database
    (docs/SCHEDULER.md)."""
    ttl = get_settings().alert_health_summary_ttl_seconds
    summary, cached = health_summary_cache.get(ttl, lambda: build_health_summary(db))
    # Lets a browser or CDN in front of the API reuse it too.
    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    return AlertHealthSummaryResponse(**summary, cached=cached, cache_ttl_seconds=ttl)


@router.post("/{alert_id}/ack", response_model=AlertResponse)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertResponse:
    """Mark an active alert as acknowledged ("I have seen this").

    Acknowledging does NOT resolve it: the underlying condition is still
    there, so the alert keeps counting toward the engine's clear-run logic
    and still resolves only when the condition actually goes away. An
    already-acknowledged alert returns unchanged (idempotent); a resolved
    one is a 409, since acknowledging a finished event is meaningless."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    if alert.status == STATUS_RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Alert is already resolved and cannot be acknowledged."
        )
    if alert.status != STATUS_ACKNOWLEDGED:
        alert.status = STATUS_ACKNOWLEDGED
        db.commit()
        db.refresh(alert)
        # An acknowledged alert no longer colours the banner (see /active).
        health_summary_cache.invalidate()
    return AlertResponse.model_validate(alert)
