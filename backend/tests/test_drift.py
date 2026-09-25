"""Tests for backend/app/services/drift.py (Phase 8) and
GET /api/v1/monitoring/drift: PSI math on synthetic distributions
(identical -> ~0/stable, artificially shifted -> alert), the honest
insufficient-data path (fresh DB and/or missing reference), and a real
per-feature PSI response from 60 directly-seeded prediction_logs rows."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from app.db import PredictionLog, get_session_factory
from app.services import drift as d

# --- band_for_psi() -----------------------------------------------------

def test_band_for_psi_stable_below_warn():
    assert d.band_for_psi(0.05, warn=0.1, alert=0.25) == d.STABLE


def test_band_for_psi_warning_at_exact_warn_boundary():
    assert d.band_for_psi(0.1, warn=0.1, alert=0.25) == d.WARNING


def test_band_for_psi_significant_at_exact_alert_boundary():
    assert d.band_for_psi(0.25, warn=0.1, alert=0.25) == d.SIGNIFICANT_DRIFT


def test_band_for_psi_significant_above_alert():
    assert d.band_for_psi(1.5, warn=0.1, alert=0.25) == d.SIGNIFICANT_DRIFT


# --- _psi_from_counts() ---------------------------------------------------

def test_psi_identical_counts_is_zero():
    counts = [10, 20, 30, 40]
    assert d._psi_from_counts(counts, counts) == pytest.approx(0.0, abs=1e-9)


def test_psi_shifted_counts_is_large():
    reference = [90, 5, 5]
    current = [5, 5, 90]
    psi = d._psi_from_counts(reference, current)
    assert psi > 0.25  # comfortably in the "significant_drift" band


def test_psi_laplace_smoothing_tames_small_sample_zero_bin_noise():
    """A live window with one bin at exactly 0 purely from small-sample luck
    (not real drift) must not swing PSI into "significant_drift" the way a
    fixed-epsilon-on-proportion floor would (this was a real bug — see
    docs/DRIFT.md's "Caveat" section)."""
    reference = [50, 48, 2]  # a real, if small, share in the third bin
    current = [50, 48, 0]  # same shape, third bin empty by sampling chance
    psi = d._psi_from_counts(reference, current)
    assert psi < 0.1


# --- _numeric_drift() -----------------------------------------------------

def _reference_for(values, n_bins=20):
    counts, edges = np.histogram(np.asarray(values, dtype=float), bins=n_bins)
    return {
        "hist_edges": edges.tolist(),
        "hist_counts": counts.tolist(),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def test_numeric_drift_identical_values_is_exactly_stable():
    rng = np.random.default_rng(42)
    training_values = rng.normal(loc=30.0, scale=3.0, size=500).tolist()
    reference = _reference_for(training_values)

    # The exact same values as the reference -> byte-identical bin counts.
    result = d._numeric_drift(reference, training_values)
    assert result["psi"] == pytest.approx(0.0, abs=1e-9)
    assert d.band_for_psi(result["psi"], warn=0.1, alert=0.25) == d.STABLE


def test_numeric_drift_realistic_resample_never_reads_significant_drift():
    """A DRIFT_WINDOW-sized (200-sample) resample from the SAME population
    as the reference — the realistic "no real drift" case this endpoint
    runs against every day. Smoothing tames the worst of the small-sample
    noise but doesn't eliminate it entirely (see docs/DRIFT.md's honestly-
    documented caveat) — an occasional "warning" from pure noise is
    expected and acceptable; landing in "significant_drift" (comfortably
    below the 0.25 threshold here) would not be."""
    rng = np.random.default_rng(42)
    training_values = rng.normal(loc=30.0, scale=3.0, size=2000)
    reference = _reference_for(training_values)

    current_values = rng.choice(training_values, size=200, replace=False)
    result = d._numeric_drift(reference, current_values)
    assert result["psi"] < 0.2
    assert d.band_for_psi(result["psi"], warn=0.1, alert=0.25) in (d.STABLE, d.WARNING)


def test_numeric_drift_shifted_distribution_is_significant():
    rng = np.random.default_rng(42)
    training_values = rng.normal(loc=30.0, scale=3.0, size=500).tolist()
    reference = _reference_for(training_values)

    # Values entirely outside the training range — clipped into the
    # outermost bin, not dropped, so this must show up as strong drift.
    current_values = (rng.normal(loc=90.0, scale=2.0, size=60)).tolist()
    result = d._numeric_drift(reference, current_values)
    assert result["psi"] >= 0.25
    assert d.band_for_psi(result["psi"], warn=0.1, alert=0.25) == d.SIGNIFICANT_DRIFT


# --- _categorical_drift() -------------------------------------------------

def test_categorical_drift_identical_proportions_is_stable():
    reference_counts = {"wheat": 50, "cotton": 30, "rice": 20}
    current_values = ["wheat"] * 50 + ["cotton"] * 30 + ["rice"] * 20
    result = d._categorical_drift(reference_counts, current_values)
    assert result["psi"] < 0.1


def test_categorical_drift_concentrated_shift_is_significant():
    reference_counts = {"wheat": 34, "cotton": 33, "rice": 33}
    current_values = ["wheat"] * 60  # 100% wheat vs. training's ~1/3
    result = d._categorical_drift(reference_counts, current_values)
    assert result["psi"] >= 0.25


def test_categorical_drift_handles_a_brand_new_category():
    """A category never seen in training is real drift, not an error."""
    reference_counts = {"wheat": 50, "cotton": 50}
    current_values = ["maize"] * 60
    result = d._categorical_drift(reference_counts, current_values)
    assert result["psi"] > 0
    assert "maize" in result["current_hist"]["edges"]


# --- DriftService.compute() ------------------------------------------------

def _fake_model_service(tmp_path, reference: dict | None, version: str = "vtest"):
    version_dir = tmp_path / version
    version_dir.mkdir(parents=True, exist_ok=True)
    if reference is not None:
        (version_dir / "reference_distribution.json").write_text(json.dumps(reference))
    return SimpleNamespace(model_root=tmp_path, version=version)


def _seed_prediction_logs(rows: list[dict]) -> None:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        for row in rows:
            db.add(
                PredictionLog(
                    district=row.get("district", "Lahore"),
                    crop_type=row.get("crop_type", "wheat"),
                    soil_moisture_pct=row["soil_moisture_pct"],
                    canal_flow_cusecs=row["canal_flow_cusecs"],
                    temperature_c=row["temperature_c"],
                    humidity_pct=row["humidity_pct"],
                    rainfall_mm=row["rainfall_mm"],
                    evapotranspiration_mm=row["evapotranspiration_mm"],
                    recommendation_mm=10.0,
                    source="model_prediction",
                    model_version="vtest",
                )
            )
        db.commit()
    finally:
        db.close()


def _full_reference_distribution(base: dict, categorical: dict | None = None) -> dict:
    """Builds a complete 6-numeric + 2-categorical reference_distribution.json
    from a dict of {feature_name: list_of_values} plus category counts —
    mirrors ml/pipeline.py's compute_reference_distribution() output shape."""
    numeric = {name: _reference_for(values) for name, values in base.items()}
    categorical = categorical or {
        "district": {"Lahore": 60, "Karachi": 40},
        "crop_type": {"wheat": 60, "cotton": 40},
    }
    return {"n_rows": 100, "n_bins": 20, "numeric": numeric, "categorical": categorical}


def test_compute_insufficient_data_on_fresh_db(tmp_path):
    reference = _full_reference_distribution({name: [30.0] * 100 for name in d.DRIFT_NUMERIC_FEATURES})
    model_service = _fake_model_service(tmp_path, reference)
    service = d.DriftService(model_service)

    db = get_session_factory()()
    try:
        report = service.compute(db)
    finally:
        db.close()

    assert report.status == d.INSUFFICIENT_DATA
    assert report.samples_available == 0
    assert report.features == []
    assert report.reference_model_version == "vtest"


def test_compute_insufficient_data_when_reference_missing(tmp_path, monkeypatch):
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("DRIFT_MIN_SAMPLES", "5")
    config_module.get_settings.cache_clear()
    try:
        _seed_prediction_logs(
            [
                {
                    "soil_moisture_pct": 25.0,
                    "canal_flow_cusecs": 300.0,
                    "temperature_c": 30.0,
                    "humidity_pct": 45.0,
                    "rainfall_mm": 2.0,
                    "evapotranspiration_mm": 5.0,
                }
                for _ in range(10)
            ]
        )
        # A model version directory with no reference_distribution.json at all.
        model_service = _fake_model_service(tmp_path, reference=None, version="vtest-no-ref")
        service = d.DriftService(model_service)

        db = get_session_factory()()
        try:
            report = service.compute(db)
        finally:
            db.close()

        assert report.status == d.INSUFFICIENT_DATA
        assert report.samples_available == 10
    finally:
        monkeypatch.delenv("DRIFT_MIN_SAMPLES", raising=False)
        config_module.get_settings.cache_clear()


def test_compute_with_seeded_rows_matching_reference_is_stable(tmp_path, monkeypatch):
    """A realistic DRIFT_WINDOW-sized (200-row) window drawn from the exact
    same population/category split as the reference — the everyday "no real
    drift" case — must land in stable/warning, never significant_drift."""
    import app.config as config_module

    rng = np.random.default_rng(7)
    n = 200
    base_values = {
        "temperature_c": rng.normal(30.0, 2.0, n).tolist(),
        "humidity_pct": rng.normal(45.0, 5.0, n).tolist(),
        "rainfall_mm": rng.normal(2.0, 0.5, n).tolist(),
        "evapotranspiration_mm": rng.normal(5.0, 0.5, n).tolist(),
        "canal_flow_cusecs": rng.normal(300.0, 20.0, n).tolist(),
        "soil_moisture_pct": rng.normal(25.0, 3.0, n).tolist(),
    }
    # Exactly the 60/40 split (120/80 of 200) both reference and seeded rows share.
    categorical = {
        "district": {"Lahore": 120, "Karachi": 80},
        "crop_type": {"wheat": 120, "cotton": 80},
    }
    reference = _full_reference_distribution(base_values, categorical)
    model_service = _fake_model_service(tmp_path, reference)

    monkeypatch.setenv("DRIFT_MIN_SAMPLES", "50")
    config_module.get_settings.cache_clear()
    try:
        rows = [
            {
                "district": "Lahore" if i % 5 < 3 else "Karachi",
                "crop_type": "wheat" if i % 5 < 3 else "cotton",
                "temperature_c": base_values["temperature_c"][i],
                "humidity_pct": base_values["humidity_pct"][i],
                "rainfall_mm": base_values["rainfall_mm"][i],
                "evapotranspiration_mm": base_values["evapotranspiration_mm"][i],
                "canal_flow_cusecs": base_values["canal_flow_cusecs"][i],
                "soil_moisture_pct": base_values["soil_moisture_pct"][i],
            }
            for i in range(n)
        ]
        _seed_prediction_logs(rows)

        service = d.DriftService(model_service)
        db = get_session_factory()()
        try:
            report = service.compute(db)
        finally:
            db.close()

        assert report.samples_available == 200
        assert len(report.features) == 8
        assert report.status == d.STABLE  # drawn from the exact same population/category split
    finally:
        monkeypatch.delenv("DRIFT_MIN_SAMPLES", raising=False)
        config_module.get_settings.cache_clear()


def test_compute_with_shifted_rows_is_significant_drift(tmp_path, monkeypatch):
    import app.config as config_module

    rng = np.random.default_rng(11)
    base_values = {name: rng.normal(30.0, 2.0, 200).tolist() for name in d.DRIFT_NUMERIC_FEATURES}
    reference = _full_reference_distribution(base_values)
    model_service = _fake_model_service(tmp_path, reference)

    monkeypatch.setenv("DRIFT_MIN_SAMPLES", "50")
    config_module.get_settings.cache_clear()
    try:
        # All 60 rows use the same, single district/crop (100% concentration
        # vs. the reference's 60/40 split) and numeric values far outside
        # the training range — a strong, unambiguous drift signal.
        rows = [
            {
                "district": "Peshawar",
                "crop_type": "rice",
                "temperature_c": 90.0,
                "humidity_pct": 90.0,
                "rainfall_mm": 90.0,
                "evapotranspiration_mm": 90.0,
                "canal_flow_cusecs": 900.0,
                "soil_moisture_pct": 95.0,
            }
            for _ in range(60)
        ]
        _seed_prediction_logs(rows)

        service = d.DriftService(model_service)
        db = get_session_factory()()
        try:
            report = service.compute(db)
        finally:
            db.close()

        assert report.status == d.SIGNIFICANT_DRIFT
        worst = max(report.features, key=lambda f: f.psi)
        assert worst.band == d.SIGNIFICANT_DRIFT
    finally:
        monkeypatch.delenv("DRIFT_MIN_SAMPLES", raising=False)
        config_module.get_settings.cache_clear()


# --- GET /api/v1/monitoring/drift ------------------------------------------

def test_drift_endpoint_insufficient_data_on_fresh_db(client):
    response = client.get("/api/v1/monitoring/drift")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["samples_available"] == 0
    assert body["features"] == []
    assert body["reference_model_version"]  # the real active model version, not null


def test_drift_endpoint_with_60_seeded_rows_returns_per_feature_psi(client):
    rows = [
        {
            "district": "Lahore",
            "crop_type": "wheat",
            "temperature_c": 30.0 + (i % 5),
            "humidity_pct": 45.0,
            "rainfall_mm": 2.0,
            "evapotranspiration_mm": 5.0,
            "canal_flow_cusecs": 300.0,
            "soil_moisture_pct": 25.0,
        }
        for i in range(60)
    ]
    _seed_prediction_logs(rows)

    response = client.get("/api/v1/monitoring/drift")
    assert response.status_code == 200
    body = response.json()

    assert body["samples_available"] == 60
    assert body["window_used"] == 200
    assert body["status"] in ("stable", "warning", "significant_drift")
    assert len(body["features"]) == 8
    feature_names = {f["name"] for f in body["features"]}
    assert feature_names == set(d.DRIFT_NUMERIC_FEATURES) | set(d.DRIFT_CATEGORICAL_FEATURES)
    for feature in body["features"]:
        assert feature["band"] in ("stable", "warning", "significant_drift")
        assert len(feature["reference_hist"]["edges"]) == len(feature["reference_hist"]["counts"]) or len(
            feature["reference_hist"]["edges"]
        ) == len(feature["reference_hist"]["counts"]) + 1
        assert len(feature["current_hist"]["counts"]) > 0
