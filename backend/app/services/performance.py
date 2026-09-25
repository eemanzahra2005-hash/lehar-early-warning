"""Phase 10: honest model-performance tracking from REAL recorded outcomes
only. Per CLAUDE.md rule 4, this never fabricates a metric or a data point —
GET /api/v1/monitoring/performance reports status="no_actuals_recorded"
until at least one user has recorded a real outcome via
POST /api/v1/history/{id}/actual (app/db.py's ActualObservation).
"""

import math
from dataclasses import dataclass, field
from datetime import date as date_cls

from sqlalchemy.orm import Session

from app.db import ActualObservation, PredictionLog


@dataclass
class PerformancePoint:
    date: date_cls
    error: float


@dataclass
class PerformanceReport:
    status: str
    count: int
    rolling_mae: float | None = None
    rolling_rmse: float | None = None
    series: list[PerformancePoint] = field(default_factory=list)


class PerformanceService:
    """Joins every actual_observations row to its prediction_logs row and
    computes real MAE/RMSE plus a chronological signed-error series. A
    plain on-demand DB read (no caching, unlike WeatherService/FloodService)
    — this table only grows one row at a time from a human manually
    recording an outcome, so there's no request-rate pressure to cache."""

    def compute(self, db: Session) -> PerformanceReport:
        rows = (
            db.query(ActualObservation, PredictionLog)
            .join(PredictionLog, ActualObservation.prediction_log_id == PredictionLog.id)
            .order_by(ActualObservation.observed_at.asc())
            .all()
        )
        if not rows:
            return PerformanceReport(status="no_actuals_recorded", count=0)

        errors = [actual.actual_irrigation_mm - log.recommendation_mm for actual, log in rows]
        mae = sum(abs(e) for e in errors) / len(errors)
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        series = [
            PerformancePoint(date=actual.observed_at.date(), error=round(error, 2))
            for (actual, _log), error in zip(rows, errors)
        ]

        return PerformanceReport(
            status="ok",
            count=len(rows),
            rolling_mae=round(mae, 3),
            rolling_rmse=round(rmse, 3),
            series=series,
        )
