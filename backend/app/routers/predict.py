"""POST /api/v1/predict — the core irrigation recommendation endpoint."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_optional
from app.db import Field as FieldModel
from app.db import PredictionLog, User, get_db
from app.dependencies import (
    get_explain_service,
    get_flood_service,
    get_model_service,
    get_risk_service,
    get_weather_service,
)
from app.metrics import prediction_latency_seconds, predictions_total
from app.rate_limit import limiter, predict_rate_limit
from app.schemas import PredictRequest, PredictResponse, WeatherUsed
from app.services.explain import ExplainService
from app.services.flood import FloodService
from app.services.ml_model import ModelService
from app.services.risk import RiskService
from app.services.soil import SOURCE_MANUAL
from app.services.weather import WeatherService
from app.validators import validate_crop, validate_district

FLOOD_OVERRIDE_REASON = "Flood/heavy-rain risk — irrigation not advised (see docs/FLOOD_RISK.md)."

logger = logging.getLogger("app.predict")

router = APIRouter(tags=["predict"])

MANUAL_WEATHER_FIELDS = (
    "manual_temperature_c",
    "manual_humidity_pct",
    "manual_rainfall_mm",
    "manual_evapotranspiration_mm",
)


def _resolve_weather(payload: PredictRequest, weather_service: WeatherService) -> dict:
    if payload.use_live_weather:
        live = weather_service.fetch(payload.district)
        return {**live, "source": "open-meteo"}

    missing = [name for name in MANUAL_WEATHER_FIELDS if getattr(payload, name) is None]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"use_live_weather is false but missing manual weather fields: {missing}",
        )
    return {
        "temperature_c": payload.manual_temperature_c,
        "humidity_pct": payload.manual_humidity_pct,
        "rainfall_mm": payload.manual_rainfall_mm,
        "evapotranspiration_mm": payload.manual_evapotranspiration_mm,
        "source": "manual",
    }


def _resolve_soil_moisture(payload: PredictRequest, weather_service: WeatherService) -> dict:
    """Phase 16: which soil moisture value this prediction uses, and where it
    came from (docs/SOIL_MOISTURE.md). Unlike live weather, a failed live soil
    fetch never fails the request — it falls back to the request's own
    soil_moisture_pct and says so in `note`."""
    manual = {"value": payload.soil_moisture_pct, "source": SOURCE_MANUAL, "layers": None, "note": None}
    if not payload.use_live_soil:
        return manual

    try:
        reading = weather_service.fetch_soil_moisture(payload.district)
    except Exception as exc:
        # WeatherService's HTTPException details are already clean,
        # user-safe messages; anything else gets a generic reason.
        reason = exc.detail if isinstance(exc, HTTPException) else "unexpected error"
        logger.warning(
            "Live soil moisture unavailable for %s; using the manual value", payload.district, exc_info=True
        )
        return {**manual, "note": f"Live soil moisture unavailable ({reason}) — used the manual value instead."}

    return {
        "value": reading["soil_moisture_pct"],
        "source": reading["source"],
        "layers": reading["layers"],
        "note": None,
    }


def _resolve_field(payload: PredictRequest, current_user: User | None, db: Session) -> FieldModel | None:
    if payload.field_id is None:
        return None
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="field_id requires authentication"
        )
    field = db.query(FieldModel).filter(FieldModel.id == payload.field_id).first()
    if field is None or field.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    return field


@router.post("/predict", response_model=PredictResponse)
@limiter.limit(predict_rate_limit)
def predict(
    request: Request,
    payload: PredictRequest,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
    model_service: ModelService = Depends(get_model_service),
    weather_service: WeatherService = Depends(get_weather_service),
    flood_service: FloodService = Depends(get_flood_service),
    explain_service: ExplainService = Depends(get_explain_service),
    risk_service: RiskService = Depends(get_risk_service),
) -> PredictResponse:
    validate_district(payload.district)
    validate_crop(payload.crop_type)

    with prediction_latency_seconds.time():
        field = _resolve_field(payload, current_user, db)
        weather = _resolve_weather(payload, weather_service)
        # The one soil moisture value used everywhere below (risk, fallback
        # rule, model, prediction_logs, response) — live or manual.
        soil = _resolve_soil_moisture(payload, weather_service)
        soil_moisture_pct = soil["value"]

        # Farm Risk Score (docs/RISK_SCORE.md): pure arithmetic on the same
        # inputs shown elsewhere in the response, independent of the ML model —
        # always computed, regardless of prediction source.
        risk = risk_service.compute(
            soil_moisture_pct=soil_moisture_pct,
            evapotranspiration_mm=weather["evapotranspiration_mm"],
            temperature_c=weather["temperature_c"],
            canal_flow_cusecs=payload.canal_flow_cusecs,
            rainfall_mm=weather["rainfall_mm"],
        )

        reason = None
        explanation = None
        confidence = None
        if payload.simulate_sensor_fault:
            # Documented rule-based fallback: bypass the model entirely so the
            # app degrades gracefully when live sensor data can't be trusted.
            # No SHAP explanation makes sense here — the model was never run.
            recommendation = (35.0 - soil_moisture_pct) * 0.9
            source = "fallback_rule_based"
            reason = (
                "Simulated sensor fault: bypassed the ML model and used the "
                "rule-based fallback recommendation = max(0, (35 - soil_moisture_pct) * 0.9)."
            )
            model_version_used = None
            model_metrics = None
        else:
            row = model_service.build_feature_row(
                temperature_c=weather["temperature_c"],
                humidity_pct=weather["humidity_pct"],
                rainfall_mm=weather["rainfall_mm"],
                evapotranspiration_mm=weather["evapotranspiration_mm"],
                canal_flow_cusecs=payload.canal_flow_cusecs,
                soil_moisture_pct=soil_moisture_pct,
                district=payload.district,
                crop_type=payload.crop_type,
                on_date=date.today(),
            )
            recommendation = model_service.predict_row(row)
            source = "model_prediction"
            model_version_used = model_service.version
            model_metrics = model_service.metrics

            # Explainability (Phase 6): never allowed to break the prediction.
            # ExplainService already catches its own failures internally and
            # returns None; this try/except is a second, belt-and-suspenders
            # layer in case a swapped-in explain_service doesn't (see
            # test_predict.py's broken-explainer test).
            try:
                explanation = explain_service.explain(row)
            except Exception:
                logger.exception("Explanation failed unexpectedly")
                explanation = None
            try:
                confidence = explain_service.confidence(row)
            except Exception:
                logger.exception("Confidence interval failed unexpectedly")
                confidence = None

        recommendation = round(max(0.0, recommendation), 1)

        # Flood cross-link (docs/FLOOD_RISK.md): a HIGH flood band overrides the
        # recommendation to 0.0 regardless of how it was computed above — reads
        # from FloodService's own in-memory cache (never an extra network call
        # on the predict path), and get_band_for() never raises, so an
        # unavailable flood provider silently leaves the prediction untouched.
        model_raw_mm = None
        if flood_service.get_band_for(payload.district) == "HIGH":
            model_raw_mm = recommendation
            recommendation = 0.0
            source = "rule_flood_override"
            reason = FLOOD_OVERRIDE_REASON

    predictions_total.labels(
        source=source, district=payload.district, model_version=model_version_used or "none"
    ).inc()

    try:
        log = PredictionLog(
            user_id=current_user.id if current_user else None,
            field_id=field.id if field else None,
            district=payload.district,
            crop_type=payload.crop_type,
            soil_moisture_pct=soil_moisture_pct,
            canal_flow_cusecs=payload.canal_flow_cusecs,
            temperature_c=weather["temperature_c"],
            humidity_pct=weather["humidity_pct"],
            rainfall_mm=weather["rainfall_mm"],
            evapotranspiration_mm=weather["evapotranspiration_mm"],
            recommendation_mm=recommendation,
            source=source,
            model_version=model_version_used,
            risk_score=risk["score"],
            risk_band=risk["band"],
        )
        db.add(log)
        db.commit()
    except Exception:
        # Logging must never break the prediction response.
        db.rollback()
        logger.exception("Failed to write prediction_logs entry")

    return PredictResponse(
        irrigation_recommendation_mm=recommendation,
        source=source,
        model_version=model_version_used,
        weather_used=WeatherUsed(**weather),
        inputs_used={
            "district": payload.district,
            "crop_type": payload.crop_type,
            "soil_moisture_pct": soil_moisture_pct,
            "canal_flow_cusecs": payload.canal_flow_cusecs,
        },
        model_metrics=model_metrics,
        reason=reason,
        model_raw_mm=model_raw_mm,
        explanation=explanation,
        confidence=confidence,
        risk=risk,
        soil_moisture_used=soil_moisture_pct,
        soil_moisture_source=soil["source"],
        soil_moisture_layers=soil["layers"],
        soil_moisture_note=soil["note"],
    )
