"""POST /api/v1/compare — live weather + model recommendation for 2-6
districts side by side. A single district's weather/prediction failure is
returned as an error entry for that district only, never a whole-request
failure (see CompareDistrictResult.error)."""

from fastapi import APIRouter, Depends

from app.dependencies import get_model_service, get_risk_service, get_weather_service
from app.schemas import CompareDistrictResult, CompareRequest, CompareResponse, WeatherUsed
from app.services.ml_model import ModelService
from app.services.risk import RiskService
from app.services.weather import WeatherService
from app.validators import validate_crop, validate_district

router = APIRouter(tags=["compare"])


def _compare_one(
    district: str,
    payload: CompareRequest,
    weather_service: WeatherService,
    model_service: ModelService,
    risk_service: RiskService,
) -> CompareDistrictResult:
    try:
        validate_district(district)
    except Exception:
        return CompareDistrictResult(district=district, error=f"Unknown district: {district}")

    try:
        weather = weather_service.fetch(district)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return CompareDistrictResult(district=district, error=f"Weather unavailable: {detail}")

    try:
        recommendation = model_service.predict(
            temperature_c=weather["temperature_c"],
            humidity_pct=weather["humidity_pct"],
            rainfall_mm=weather["rainfall_mm"],
            evapotranspiration_mm=weather["evapotranspiration_mm"],
            canal_flow_cusecs=payload.canal_flow_cusecs,
            soil_moisture_pct=payload.soil_moisture_pct,
            district=district,
            crop_type=payload.crop_type,
        )
    except Exception as exc:
        return CompareDistrictResult(district=district, error=f"Prediction failed: {exc}")

    risk = risk_service.compute(
        soil_moisture_pct=payload.soil_moisture_pct,
        evapotranspiration_mm=weather["evapotranspiration_mm"],
        temperature_c=weather["temperature_c"],
        canal_flow_cusecs=payload.canal_flow_cusecs,
        rainfall_mm=weather["rainfall_mm"],
    )

    return CompareDistrictResult(
        district=district,
        weather=WeatherUsed(**weather, source="open-meteo"),
        recommendation_mm=round(max(0.0, recommendation), 1),
        model_version=model_service.version,
        risk=risk,
    )


@router.post("/compare", response_model=CompareResponse)
def compare_districts(
    payload: CompareRequest,
    weather_service: WeatherService = Depends(get_weather_service),
    model_service: ModelService = Depends(get_model_service),
    risk_service: RiskService = Depends(get_risk_service),
) -> CompareResponse:
    validate_crop(payload.crop_type)

    results = [
        _compare_one(district, payload, weather_service, model_service, risk_service) for district in payload.districts
    ]

    return CompareResponse(
        crop_type=payload.crop_type,
        soil_moisture_pct=payload.soil_moisture_pct,
        canal_flow_cusecs=payload.canal_flow_cusecs,
        results=results,
    )
