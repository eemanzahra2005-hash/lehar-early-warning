"""Prediction history endpoints (auth required)."""

from datetime import date as date_cls
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import ActualObservation, PredictionLog, User, get_db
from app.schemas import ActualObservationRequest, PredictionLogResponse

router = APIRouter(tags=["history"])


@router.get("/history", response_model=list[PredictionLogResponse])
def get_history(
    limit: int = Query(50, ge=1, le=500),
    district: str | None = None,
    crop: str | None = None,
    field_id: int | None = None,
    date_from: date_cls | None = Query(None, alias="from"),
    date_to: date_cls | None = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PredictionLog]:
    query = db.query(PredictionLog).filter(PredictionLog.user_id == current_user.id)
    if district:
        query = query.filter(PredictionLog.district == district)
    if crop:
        query = query.filter(PredictionLog.crop_type == crop)
    if field_id is not None:
        query = query.filter(PredictionLog.field_id == field_id)
    if date_from is not None:
        # `from`/`to` come from an HTML <input type="date">, i.e. the browser's local
        # calendar day. created_at is stored as a true UTC instant, so a naive
        # datetime.astimezone(utc) (which Python assumes is in system local time) converts
        # the local day boundary to the right UTC instant instead of misreading it as UTC.
        query = query.filter(PredictionLog.created_at >= datetime.combine(date_from, time.min).astimezone(timezone.utc))
    if date_to is not None:
        query = query.filter(PredictionLog.created_at <= datetime.combine(date_to, time.max).astimezone(timezone.utc))
    return query.order_by(PredictionLog.created_at.desc()).limit(limit).all()


@router.post(
    "/history/{prediction_id}/actual",
    response_model=PredictionLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_actual(
    prediction_id: int,
    payload: ActualObservationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PredictionLog:
    """Phase 10: records a real irrigation outcome against one of the
    caller's own past predictions — the input to
    GET /api/v1/monitoring/performance's honest MAE/RMSE. 404s for a
    prediction that doesn't exist or belongs to someone else (same
    non-owner-disclosure pattern as predict.py's _resolve_field), 409 if
    this prediction already has a recorded outcome (one-to-one, see
    app/db.py's ActualObservation)."""
    log = db.query(PredictionLog).filter(PredictionLog.id == prediction_id).first()
    if log is None or log.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found")

    existing = (
        db.query(ActualObservation).filter(ActualObservation.prediction_log_id == prediction_id).first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An actual outcome has already been recorded for this prediction.",
        )

    observation = ActualObservation(
        prediction_log_id=prediction_id,
        actual_irrigation_mm=payload.actual_irrigation_mm,
        note=payload.note,
    )
    db.add(observation)
    db.commit()
    db.refresh(log)
    return log
