"""Phase 12: gathers everything a report (Excel or PDF, see report_xlsx.py /
report_pdf.py) needs into one plain dict — REAL data only, reusing the exact
same services the rest of the app uses (WeatherService, ModelService,
RiskService, ExplainService), mirroring the pattern already established by
AssistantService (app/services/assistant.py). Every section is independently
best-effort so one broken upstream (e.g. Open-Meteo down) degrades that
section only, never a 500 — the report still generates (see docs on
`weather`/`forecast` possibly being None below).

Never invents a number: an empty prediction history yields an explicit
`history` == [] and `latest_prediction` == None, rendered by the report
builders as a plain "No predictions recorded yet" row/paragraph rather than
an error or a fabricated example.
"""

import logging
from datetime import date as date_cls
from datetime import datetime, time, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import Field as FieldModel
from app.db import PredictionLog, User
from app.services.explain import ExplainService
from app.services.ml_model import ModelService
from app.services.weather import WeatherService
from ml.districts import DISTRICTS

logger = logging.getLogger("app.report")

# Fallback district when the caller gives no field_id/district AND the user
# has no saved fields/prediction history to infer one from (e.g. a
# brand-new, fresh account) — Lahore is Pakistan's second-largest city and
# already used as an illustrative example elsewhere in this codebase's docs.
DEFAULT_REPORT_DISTRICT = "Lahore"

FORECAST_DAYS = 7
SHAP_FACTORS_LIMIT = 3


def resolve_district(
    *,
    requested_district: str | None,
    field: FieldModel | None,
    user: User | None,
    db: Session,
) -> str:
    """Priority: explicit ?district= param > the given field's district >
    the user's most recent prediction's district > the user's first saved
    field's district > DEFAULT_REPORT_DISTRICT. Always returns a valid,
    known district (never raises) so the report can always generate."""
    if requested_district and requested_district in DISTRICTS:
        return requested_district
    if field is not None:
        return field.district
    if user is not None:
        latest = (
            db.query(PredictionLog)
            .filter(PredictionLog.user_id == user.id)
            .order_by(PredictionLog.created_at.desc())
            .first()
        )
        if latest is not None:
            return latest.district
        first_field = db.query(FieldModel).filter(FieldModel.user_id == user.id).order_by(FieldModel.id).first()
        if first_field is not None:
            return first_field.district
    return DEFAULT_REPORT_DISTRICT


def _weather_section(weather_service: WeatherService, district: str) -> dict | None:
    try:
        return weather_service.fetch(district)
    except Exception:
        logger.warning("Report: current weather unavailable for %s", district, exc_info=True)
        return None


def _forecast_section(weather_service: WeatherService, district: str) -> list[dict] | None:
    try:
        return weather_service.fetch_forecast(district, days=FORECAST_DAYS)
    except Exception:
        logger.warning("Report: forecast unavailable for %s", district, exc_info=True)
        return None


def _history_query(
    db: Session,
    user: User,
    *,
    field_id: int | None,
    district: str | None,
    date_from: date_cls | None,
    date_to: date_cls | None,
):
    """Mirrors app/routers/history.py's GET /history filtering exactly, so
    the report's history table always matches what the History page shows
    for the same filters."""
    query = db.query(PredictionLog).filter(PredictionLog.user_id == user.id)
    if district:
        query = query.filter(PredictionLog.district == district)
    if field_id is not None:
        query = query.filter(PredictionLog.field_id == field_id)
    if date_from is not None:
        query = query.filter(PredictionLog.created_at >= datetime.combine(date_from, time.min).astimezone(timezone.utc))
    if date_to is not None:
        query = query.filter(PredictionLog.created_at <= datetime.combine(date_to, time.max).astimezone(timezone.utc))
    return query.order_by(PredictionLog.created_at.desc())


def _latest_prediction_section(
    model_service: ModelService,
    explain_service: ExplainService,
    latest: PredictionLog | None,
) -> dict | None:
    if latest is None:
        return None
    entry = {
        "id": latest.id,
        "district": latest.district,
        "crop_type": latest.crop_type,
        "soil_moisture_pct": latest.soil_moisture_pct,
        "canal_flow_cusecs": latest.canal_flow_cusecs,
        "temperature_c": latest.temperature_c,
        "humidity_pct": latest.humidity_pct,
        "rainfall_mm": latest.rainfall_mm,
        "evapotranspiration_mm": latest.evapotranspiration_mm,
        "recommendation_mm": latest.recommendation_mm,
        "source": latest.source,
        "model_version": latest.model_version,
        "risk_score": latest.risk_score,
        "risk_band": latest.risk_band,
        "created_at": latest.created_at,
        "top_factors": None,
    }
    try:
        # Real SHAP recomputed from this exact stored row — same
        # never-persisted-so-recompute-live pattern as
        # AssistantService._latest_prediction_section.
        row = model_service.build_feature_row(
            temperature_c=latest.temperature_c,
            humidity_pct=latest.humidity_pct,
            rainfall_mm=latest.rainfall_mm,
            evapotranspiration_mm=latest.evapotranspiration_mm,
            canal_flow_cusecs=latest.canal_flow_cusecs,
            soil_moisture_pct=latest.soil_moisture_pct,
            district=latest.district,
            crop_type=latest.crop_type,
            on_date=latest.created_at.date(),
        )
        explanation = explain_service.explain(row)
        if explanation:
            entry["top_factors"] = explanation["top_factors"][:SHAP_FACTORS_LIMIT]
    except Exception:
        logger.warning("Report: SHAP recompute for latest prediction failed", exc_info=True)
    return entry


def gather_report_data(
    *,
    user: User,
    db: Session,
    model_service: ModelService,
    weather_service: WeatherService,
    explain_service: ExplainService,
    field_id: int | None,
    requested_district: str | None,
    date_from: date_cls | None,
    date_to: date_cls | None,
) -> dict:
    """Assembles every section a report needs. Raises HTTPException (404)
    only for an explicitly-requested field_id that doesn't belong to the
    caller — everything else degrades gracefully (see module docstring)."""
    field = None
    if field_id is not None:
        field = db.query(FieldModel).filter(FieldModel.id == field_id).first()
        if field is None or field.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")

    district = resolve_district(requested_district=requested_district, field=field, user=user, db=db)

    history_rows = list(
        _history_query(db, user, field_id=field_id, district=requested_district, date_from=date_from, date_to=date_to)
    )
    latest = history_rows[0] if history_rows else None

    return {
        "generated_at": datetime.now(timezone.utc),
        "user": user,
        "field": field,
        "district": district,
        "filters": {"field_id": field_id, "district": requested_district, "from": date_from, "to": date_to},
        "model_version": model_service.version,
        "model_metrics": model_service.metrics,
        "weather": _weather_section(weather_service, district),
        "forecast": _forecast_section(weather_service, district),
        "latest_prediction": _latest_prediction_section(model_service, explain_service, latest),
        "history": history_rows,
    }


def report_filename(data: dict, extension: str) -> str:
    """lehar-report-<district>-<date>.<xlsx|pdf> — shared by report_xlsx.py,
    report_pdf.py, and the router's Content-Disposition header."""
    date_str = data["generated_at"].strftime("%Y%m%d")
    district = data["district"].lower().replace(" ", "-")
    return f"lehar-report-{district}-{date_str}.{extension}"
