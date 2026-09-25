"""Tests for backend/ml/pipeline.py (Phase 7): the quality-gate decision
matrix (pure function, no I/O) and an end-to-end offline smoke test of the
full staged pipeline (load -> validate -> split -> train -> evaluate ->
quality_gate -> track -> register) against a tiny in-memory sample, writing
to tmp_path directories only — never the real dataset, registry, or MLflow
server. The MLflow tracking_uri passed is deliberately unreachable
(127.0.0.1 on an unused port) so this suite exercises the required "must
work fully offline" fallback path, regardless of whether a real `docker
compose up -d mlflow` happens to be running on the developer's machine.
"""

from types import SimpleNamespace

import pytest

from ml import pipeline as p
from ml.generate_data import generate_dataset
from ml.registry import read_registry

UNREACHABLE_MLFLOW_URI = "http://127.0.0.1:1"  # port 1 is never a real server

# Small sample: 107 districts * 20 rows/district ~= 2,140 rows — enough for a
# meaningful time-ordered split without the real dataset's training cost.
SAMPLE_ROWS_PER_DISTRICT = 20


def make_settings(max_mae=1.0, tolerance=0.05, min_r2=0.90):
    return SimpleNamespace(qg_max_mae=max_mae, qg_mae_tolerance=tolerance, qg_min_r2=min_r2)


# --- quality_gate() decision matrix ------------------------------------------

def test_gate_passes_with_no_production_model_within_ceilings():
    result = p.quality_gate({"mae": 0.5, "r2": 0.95}, None, make_settings())
    assert result.passed is True
    assert "PASS" in result.reasons[0]


def test_gate_fails_ceiling_breach_even_with_no_production_model():
    result = p.quality_gate({"mae": 1.5, "r2": 0.95}, None, make_settings())
    assert result.passed is False
    assert any("ceiling" in r.lower() for r in result.reasons)


def test_gate_passes_when_candidate_is_better_than_production():
    candidate = {"mae": 0.20, "r2": 0.98}
    production = {"mae": 0.25, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings())
    assert result.passed is True
    assert "better" in result.reasons[0].lower()


def test_gate_passes_when_candidate_is_slightly_worse_within_tolerance():
    candidate = {"mae": 0.27, "r2": 0.97}  # production + 0.02, tolerance is 0.05
    production = {"mae": 0.25, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings())
    assert result.passed is True
    assert "tolerance" in result.reasons[0].lower()


def test_gate_fails_when_candidate_is_worse_beyond_tolerance():
    candidate = {"mae": 0.40, "r2": 0.97}  # production + 0.15, tolerance is 0.05
    production = {"mae": 0.25, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings())
    assert result.passed is False
    assert any("tolerance" in r.lower() for r in result.reasons)


def test_gate_fails_on_low_r2_even_if_mae_is_fine():
    candidate = {"mae": 0.20, "r2": 0.80}
    production = {"mae": 0.25, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings())
    assert result.passed is False
    assert any("r2" in r.lower() for r in result.reasons)


def test_gate_fails_on_absolute_mae_ceiling_even_if_better_than_production():
    # Production itself is already above the (hypothetically lowered) ceiling.
    candidate = {"mae": 1.2, "r2": 0.97}
    production = {"mae": 1.4, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings(max_mae=1.0))
    assert result.passed is False
    assert any("ceiling" in r.lower() for r in result.reasons)


def test_gate_boundary_exactly_at_tolerance_passes():
    candidate = {"mae": 0.30, "r2": 0.97}  # exactly production + tolerance
    production = {"mae": 0.25, "r2": 0.97}
    result = p.quality_gate(candidate, production, make_settings(tolerance=0.05))
    assert result.passed is True


# --- validate() ---------------------------------------------------------------

def test_validate_passes_on_a_real_generated_sample():
    df = generate_dataset(rows_per_district=5)
    p.validate(df)  # must not raise


def test_validate_rejects_missing_column():
    df = generate_dataset(rows_per_district=5).drop(columns=["temperature_c"])
    with pytest.raises(ValueError, match="Missing required column"):
        p.validate(df)


def test_validate_rejects_out_of_range_value():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "humidity_pct"] = 250.0
    with pytest.raises(ValueError, match="humidity_pct"):
        p.validate(df)


def test_validate_rejects_unknown_district():
    df = generate_dataset(rows_per_district=5)
    df.loc[0, "district"] = "Atlantis"
    with pytest.raises(ValueError, match="district"):
        p.validate(df)


# --- End-to-end offline smoke test -------------------------------------------

def test_pipeline_smoke_test_passes_gate_and_writes_versioned_model(tmp_path):
    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)
    model_root = tmp_path / "model"
    mlruns_dir = tmp_path / "mlruns"

    result = p.run_pipeline(
        df=df,
        model_root=model_root,
        n_estimators=10,
        max_depth=10,
        seed=42,
        tracking_uri=UNREACHABLE_MLFLOW_URI,
        mlruns_dir=mlruns_dir,
    )

    assert result["gate_passed"] is True
    assert result["version"] is not None
    assert result["mlflow_using_remote"] is False  # confirms the offline fallback path ran
    assert result["mlflow_run_id"]
    assert mlruns_dir.exists()  # local file-tracking fallback actually wrote something

    version_dir = model_root / result["version"]
    assert (version_dir / "model.joblib").exists()
    assert (version_dir / "metrics.json").exists()
    assert (version_dir / "feature_importance.json").exists()
    assert (version_dir / "global_shap.json").exists()
    assert (version_dir / "reference_stats.json").exists()

    registry = read_registry(model_root)
    assert registry["latest"] == result["version"]
    entry = registry["versions"][result["version"]]
    assert entry["source"] == "pipeline"
    assert entry["mlflow_run_id"] == result["mlflow_run_id"]
    assert entry["gate"]["passed"] is True


def test_pipeline_second_run_compares_against_first_as_production(tmp_path):
    """A second pipeline run against the same model_root reads the first
    run's metrics as "production" and applies the tolerance check — proving
    quality_gate() is actually wired to registry.json, not just unit-tested
    in isolation above."""
    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)
    model_root = tmp_path / "model"
    mlruns_dir = tmp_path / "mlruns"

    first = p.run_pipeline(
        df=df, model_root=model_root, n_estimators=10, max_depth=10, seed=1,
        tracking_uri=UNREACHABLE_MLFLOW_URI, mlruns_dir=mlruns_dir,
    )
    assert first["gate_passed"] is True

    second = p.run_pipeline(
        df=df, model_root=model_root, n_estimators=10, max_depth=10, seed=2,
        tracking_uri=UNREACHABLE_MLFLOW_URI, mlruns_dir=mlruns_dir,
    )
    assert second["gate_passed"] is True
    assert any("production" in r.lower() or "no production" not in r.lower() for r in second["gate_reasons"])

    registry = read_registry(model_root)
    assert registry["latest"] == second["version"]
    # The first version should now be reachable via the registry, still intact.
    assert first["version"] in registry["versions"]


def test_pipeline_fail_leaves_registry_untouched(tmp_path):
    """Forces a FAIL via an unreachable QG_MIN_R2 ceiling (injected directly
    as a settings override, not real global config), and confirms
    registry.json is not created/mutated and no version directory is
    written — a known-good production model must never be auto-replaced."""
    from app.config import get_settings

    strict_settings = get_settings().model_copy(update={"qg_min_r2": 0.999999})

    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)
    model_root = tmp_path / "model"
    mlruns_dir = tmp_path / "mlruns"

    result = p.run_pipeline(
        df=df, model_root=model_root, n_estimators=5, max_depth=3, seed=42,
        tracking_uri=UNREACHABLE_MLFLOW_URI, mlruns_dir=mlruns_dir, settings=strict_settings,
    )

    assert result["gate_passed"] is False
    assert result["version"] is None
    assert not (model_root / "registry.json").exists()
