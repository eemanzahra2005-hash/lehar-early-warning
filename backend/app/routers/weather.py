"""Live weather + forecast endpoints, backed by app/services/weather.py."""

from datetime import date as date_cls

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_model_service, get_weather_service
from app.schemas import ForecastResponse, SoilMoistureResponse, WeatherResponse
from app.services.ml_model import ModelService
from app.services.weather import WeatherService
from app.validators import validate_crop, validate_district
from ml.districts import DISTRICTS

router = APIRouter(tags=["weather"])

DEMAND_NOTE = "ML estimate — assumes soil moisture stays at {soil_moisture_pct:g}% for the whole forecast window."


@router.get("/weather", response_model=WeatherResponse)
def get_weather(
    district: str,
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherResponse:
    validate_district(district)
    data = weather_service.fetch(district)
    return WeatherResponse(district=district, **data)


@router.get("/soil-moisture", response_model=SoilMoistureResponse)
def get_soil_moisture(
    district: str,
    weather_service: WeatherService = Depends(get_weather_service),
) -> SoilMoistureResponse:
    """Phase 16: the latest live soil moisture for a district, so the Predict
    page's "Use live soil moisture" toggle can show the value before a
    prediction is run. A model estimate, labelled as one — see
    docs/SOIL_MOISTURE.md. Fails exactly like GET /weather (400/502/504)."""
    validate_district(district)
    reading = weather_service.fetch_soil_moisture(district)
    return SoilMoistureResponse(district=district, **reading)


@router.get("/forecast", response_model=ForecastResponse)
def get_forecast(
    district: str,
    days: int = Query(7, ge=1, le=16),
    include_demand: bool = False,
    soil_moisture_pct: float = Query(25.0, ge=0, le=100),
    crop_type: str = "wheat",
    weather_service: WeatherService = Depends(get_weather_service),
    model_service: ModelService = Depends(get_model_service),
) -> ForecastResponse:
    validate_district(district)
    data = weather_service.fetch_forecast(district, days)

    demand_note = None
    if include_demand:
        validate_crop(crop_type)
        canal_flow_cusecs = DISTRICTS[district]["canal_flow_baseline_cusecs"]
        for day in data:
            if day["humidity_pct"] is None:
                day["irrigation_estimate_mm"] = None
                continue
            estimate = model_service.predict(
                temperature_c=day["temperature_c"],
                humidity_pct=day["humidity_pct"],
                rainfall_mm=day["rainfall_mm"],
                evapotranspiration_mm=day["evapotranspiration_mm"],
                canal_flow_cusecs=canal_flow_cusecs,
                soil_moisture_pct=soil_moisture_pct,
                district=district,
                crop_type=crop_type,
                on_date=date_cls.fromisoformat(day["date"]),
            )
            day["irrigation_estimate_mm"] = round(max(0.0, estimate), 1)
        demand_note = DEMAND_NOTE.format(soil_moisture_pct=soil_moisture_pct)

    return ForecastResponse(district=district, days=data, demand_note=demand_note)
