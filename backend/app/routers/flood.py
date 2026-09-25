"""Flood Watch endpoints.

    GET /api/v1/flood/overview          every district's Flood Risk Index
    GET /api/v1/flood/district/{name}   one district, with its daily series
    GET /api/v1/flood/forecast/{name}   the 1-3 day LEAD-TIME forecast

The first two are real GloFAS river-discharge + rainfall data combined into
a transparent Flood Risk Index — see docs/FLOOD_RISK.md for the methodology
and the "not an official flood warning" disclaimer.

The third (LEHAR Phase 2.5) is the deep-learning lead-time forecast: the
same index, computed on a small GRU's PREDICTION of where the river will be
in 1-3 days rather than on today's observation, so an alert can fire before
the flood. See docs/FLOOD_DL.md. It is off unless FLOOD_DL_ENABLED=true and
a model is registered, and says so with a 503 rather than inventing one.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_flood_forecast_service, get_flood_service
from app.schemas import FloodDistrictDetail, FloodForecastResponse, FloodOverviewResponse
from app.services.flood import FloodService
from app.services.flood_forecast import FloodForecastService

router = APIRouter(prefix="/flood", tags=["flood"])


@router.get("/overview", response_model=FloodOverviewResponse)
def get_flood_overview(service: FloodService = Depends(get_flood_service)) -> FloodOverviewResponse:
    return service.get_overview()


@router.get("/district/{district}", response_model=FloodDistrictDetail)
def get_flood_district(district: str, service: FloodService = Depends(get_flood_service)) -> FloodDistrictDetail:
    return service.get_district(district)


@router.get("/forecast/{district}", response_model=FloodForecastResponse)
def get_flood_forecast(
    district: str,
    service: FloodForecastService = Depends(get_flood_forecast_service),
) -> FloodForecastResponse:
    """The flood lead-time forecast for one district (LEHAR Phase 2.5).

    Returns the 14 observed days the model read, the discharge it predicts
    for D+1/D+2/D+3, and the Flood Risk Index band and alert level those
    predictions map to under the SAME thresholds Flood Watch already uses.

    503 whenever there is no forecast to give — the feature is disabled, no
    model is registered, this district was not in the training set, or an
    upstream reading the window needs is missing. Never a fabricated
    forecast (CLAUDE.md rule 4); the detail says which of those it was.
    """
    if not service.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=service.status()["detail"],
        )
    return service.forecast(district)
