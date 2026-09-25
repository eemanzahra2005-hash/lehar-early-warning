"""GET /api/v1/map/overview — live weather + default-conditions irrigation
recommendation for all districts, for the interactive map choropleth."""

from fastapi import APIRouter, Depends

from app.dependencies import get_map_overview_service
from app.schemas import MapOverviewResponse
from app.services.map_overview import MapOverviewService

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/overview", response_model=MapOverviewResponse)
def get_map_overview(service: MapOverviewService = Depends(get_map_overview_service)) -> MapOverviewResponse:
    return service.get_overview()
