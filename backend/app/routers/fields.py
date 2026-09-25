"""Saved-field CRUD endpoints (auth required)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import Field as FieldModel
from app.db import User, get_db
from app.schemas import FieldCreate, FieldResponse
from app.validators import validate_crop, validate_district

router = APIRouter(prefix="/fields", tags=["fields"])


@router.get("", response_model=list[FieldResponse])
def list_fields(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FieldModel]:
    return db.query(FieldModel).filter(FieldModel.user_id == current_user.id).order_by(FieldModel.id).all()


@router.post("", response_model=FieldResponse, status_code=status.HTTP_201_CREATED)
def create_field(
    payload: FieldCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FieldModel:
    validate_district(payload.district)
    validate_crop(payload.crop_type)

    field = FieldModel(
        user_id=current_user.id,
        name=payload.name,
        district=payload.district,
        crop_type=payload.crop_type,
        default_soil_moisture_pct=payload.default_soil_moisture_pct,
        default_canal_flow_cusecs=payload.default_canal_flow_cusecs,
        # LEHAR Phase 2: optional per-field IRRIGATION_DUE trigger; None
        # keeps the ALERT_IRRIGATION_THRESHOLD_MM default.
        irrigation_threshold_mm=payload.irrigation_threshold_mm,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    field_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    field = db.query(FieldModel).filter(FieldModel.id == field_id).first()
    # 404 (not 403) for someone else's field — users must never learn that a
    # given field ID exists but belongs to another account.
    if field is None or field.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    db.delete(field)
    db.commit()
