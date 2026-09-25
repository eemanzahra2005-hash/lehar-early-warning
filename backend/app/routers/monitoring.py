"""GET /api/v1/monitoring/drift — Phase 8 PSI-based data-drift monitoring.
See app/services/drift.py and docs/DRIFT.md for the methodology, and
frontend/js/views/monitoring.js for how the response is rendered.

GET /api/v1/monitoring/performance — Phase 10 honest model-performance
tracking from real recorded outcomes only (app/services/performance.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_drift_service, get_performance_service
from app.schemas import DriftFeature, DriftHistogram, DriftResponse, PerformanceResponse
from app.services.drift import DriftService
from app.services.performance import PerformanceService

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/drift", response_model=DriftResponse)
def get_drift(
    db: Session = Depends(get_db),
    drift_service: DriftService = Depends(get_drift_service),
) -> DriftResponse:
    report = drift_service.compute(db)
    return DriftResponse(
        status=report.status,
        window_used=report.window_used,
        samples_available=report.samples_available,
        reference_model_version=report.reference_model_version,
        psi_warn=report.psi_warn,
        psi_alert=report.psi_alert,
        features=[
            DriftFeature(
                name=feature.name,
                psi=feature.psi,
                band=feature.band,
                reference_hist=DriftHistogram(**feature.reference_hist),
                current_hist=DriftHistogram(**feature.current_hist),
            )
            for feature in report.features
        ],
    )


@router.get("/performance", response_model=PerformanceResponse)
def get_performance(
    db: Session = Depends(get_db),
    performance_service: PerformanceService = Depends(get_performance_service),
) -> PerformanceResponse:
    report = performance_service.compute(db)
    return PerformanceResponse(
        status=report.status,
        count=report.count,
        rolling_mae=report.rolling_mae,
        rolling_rmse=report.rolling_rmse,
        series=[{"date": point.date, "error": point.error} for point in report.series],
    )
