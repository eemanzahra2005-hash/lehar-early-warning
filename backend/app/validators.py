"""Shared request-validation helpers.

Used by the weather, predict, and fields routers so "unknown district" /
"unknown crop" always produce the same clean 400 response, instead of each
router re-implementing the same check.
"""

from fastapi import HTTPException, status

from ml.districts import DISTRICTS
from ml.feature_schema import CROPS


def validate_district(district: str) -> None:
    if district not in DISTRICTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown district: {district}")


def validate_crop(crop_type: str) -> None:
    if crop_type not in CROPS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown crop_type: {crop_type}")
