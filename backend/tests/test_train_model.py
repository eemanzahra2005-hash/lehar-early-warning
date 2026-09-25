"""Fast smoke test for backend/ml/train_model.py.

Trains a tiny RandomForest (n_estimators=10) on a ~2,000-row in-memory
sample and writes the versioned model into a tmp_path registry, so this
stays fast and never touches the real dataset or the real
backend/ml/model/ directory.
"""

import json

from ml.generate_data import generate_dataset
from ml.train_model import run_training

# 107 districts * 45 rows/district ~= 4,815 rows
SAMPLE_ROWS_PER_DISTRICT = 45


def test_training_smoke_test_on_sample(tmp_path):
    df = generate_dataset(rows_per_district=SAMPLE_ROWS_PER_DISTRICT)
    model_root = tmp_path / "model"

    metrics = run_training(df=df, model_root=model_root, n_estimators=10, max_depth=10)

    assert metrics["r2"] > 0.8
    assert (model_root / metrics["version"] / "model.joblib").exists()
    assert (model_root / metrics["version"] / "metrics.json").exists()
    assert (model_root / metrics["version"] / "feature_importance.json").exists()

    # Phase 6: global_shap.json is produced automatically by every training
    # run (shap is a pinned, installed dependency — see requirements.txt).
    global_shap_path = model_root / metrics["version"] / "global_shap.json"
    assert global_shap_path.exists()
    global_shap = json.loads(global_shap_path.read_text())
    assert global_shap["sample_size"] == min(500, len(df))
    assert set(global_shap["mean_abs_shap_mm"].keys()) == {
        "soil_moisture_pct",
        "evapotranspiration_mm",
        "rainfall_mm",
        "temperature_c",
        "humidity_pct",
        "canal_flow_cusecs",
        "district",
        "crop_type",
        "month",
        "day_of_year",
        "was_imputed",
    }

    registry_path = model_root / "registry.json"
    assert registry_path.exists()

    registry = json.loads(registry_path.read_text())
    assert registry["latest"] == metrics["version"]
    assert metrics["version"] in registry["versions"]
