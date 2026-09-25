"""Tests for Phase 10's honest model-performance tracking
(app/services/performance.py, GET /api/v1/monitoring/performance) — computed
ONLY from real prediction_logs + actual_observations pairs, never fabricated.
"""

import math

from app.db import ActualObservation, PredictionLog, get_session_factory
from app.services.performance import PerformanceService


def _seed_pair(db, *, recommendation_mm: float, actual_mm: float) -> None:
    log = PredictionLog(
        district="Lahore",
        crop_type="wheat",
        soil_moisture_pct=25.0,
        canal_flow_cusecs=300.0,
        temperature_c=30.0,
        humidity_pct=45.0,
        rainfall_mm=2.0,
        evapotranspiration_mm=5.0,
        recommendation_mm=recommendation_mm,
        source="model_prediction",
        model_version="vtest",
    )
    db.add(log)
    db.flush()
    db.add(ActualObservation(prediction_log_id=log.id, actual_irrigation_mm=actual_mm))


def test_service_reports_no_actuals_recorded_on_fresh_db():
    db = get_session_factory()()
    try:
        report = PerformanceService().compute(db)
    finally:
        db.close()

    assert report.status == "no_actuals_recorded"
    assert report.count == 0
    assert report.rolling_mae is None
    assert report.rolling_rmse is None
    assert report.series == []


def test_service_computes_exact_mae_rmse_from_two_seeded_pairs():
    db = get_session_factory()()
    try:
        # errors: 12-10=+2, 15-20=-5 -> MAE=(2+5)/2=3.5, RMSE=sqrt((4+25)/2)=sqrt(14.5)
        _seed_pair(db, recommendation_mm=10.0, actual_mm=12.0)
        _seed_pair(db, recommendation_mm=20.0, actual_mm=15.0)
        db.commit()

        report = PerformanceService().compute(db)
    finally:
        db.close()

    assert report.status == "ok"
    assert report.count == 2
    assert report.rolling_mae == 3.5
    assert report.rolling_rmse == round(math.sqrt(14.5), 3)
    assert sorted(point.error for point in report.series) == [-5.0, 2.0]


def test_performance_endpoint_empty_state_on_fresh_db(client):
    response = client.get("/api/v1/monitoring/performance")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "no_actuals_recorded",
        "count": 0,
        "rolling_mae": None,
        "rolling_rmse": None,
        "series": [],
    }


def test_performance_endpoint_computes_real_metrics(client):
    db = get_session_factory()()
    try:
        _seed_pair(db, recommendation_mm=10.0, actual_mm=12.0)
        _seed_pair(db, recommendation_mm=20.0, actual_mm=15.0)
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/monitoring/performance")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["count"] == 2
    assert body["rolling_mae"] == 3.5
    assert body["rolling_rmse"] == round(math.sqrt(14.5), 3)
    assert len(body["series"]) == 2
    assert sorted(point["error"] for point in body["series"]) == [-5.0, 2.0]
