"""Static reference/metadata endpoint (crops, districts, ...)."""

from fastapi import APIRouter

from app.schemas import MetaResponse
from ml.districts import districts_by_province, list_district_names
from ml.feature_schema import CROPS as SUPPORTED_CROPS

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaResponse)
def get_meta() -> MetaResponse:
    """Reference data the frontend needs to populate form fields.

    Districts and their climate parameters (see backend/ml/districts.py) are
    SYNTHETIC research data, not verified geographic/climate records.
    """
    return MetaResponse(
        crops=SUPPORTED_CROPS,
        districts=list_district_names(),
        districts_by_province=districts_by_province(),
        note=f"{len(list_district_names())} Pakistan districts; district climate parameters are SYNTHETIC research data",
    )
