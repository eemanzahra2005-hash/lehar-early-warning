"""
Train the baseline RandomForest irrigation-recommendation model.

Trains on the SYNTHETIC dataset produced by generate_data.py. All reported
metrics (MAE, RMSE, R2) are computed for real on a held-out, time-ordered
test split — never invented (see CLAUDE.md rule 4).

Run directly to train on the full dataset and save a new model version:
    python backend/ml/train_model.py

The input CSV path can be overridden with the DATA_PATH environment
variable (see backend/.env.example); it defaults to
data/synthetic_irrigation_dataset_pk107.csv.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

# Make `ml` importable as a package whether this file is run directly
# (`python backend/ml/train_model.py`) or imported from tests/other code.
ML_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ML_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.explain_utils import AGGREGATED_FEATURE_ORDER, aggregate_by_parent, build_parent_map  # noqa: E402

# Re-exported (not just used internally) so existing `from ml.train_model
# import FEATURE_COLUMNS` call sites (ml/pipeline.py, tests) keep working
# unchanged — the serving path (app/services/ml_model.py, explain.py,
# app/validators.py) imports these from ml.feature_schema directly instead,
# so it never has to import this module's pandas/sklearn dependencies just
# to read a plain list (LOW_MEMORY_MODE, Phase 13.1).
from ml.feature_schema import (  # noqa: E402,F401
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from ml.registry import DEFAULT_MODEL_ROOT, register_version  # noqa: E402

logger = logging.getLogger("ml.train_model")

# Global explainability (Phase 6): fixed sample size + seed so every
# training run's global_shap.json is reproducible.
GLOBAL_SHAP_SAMPLE_SIZE = 500
GLOBAL_SHAP_SAMPLE_SEED = 42

DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "synthetic_irrigation_dataset_pk107.csv"


def resolve_data_path() -> Path:
    """DATA_PATH env var if set, else the default CSV path. Relative paths
    are resolved against the project root so this works regardless of the
    current working directory."""
    raw = os.environ.get("DATA_PATH", str(DEFAULT_DATA_PATH))
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_dataset(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"])


def time_ordered_split(df: pd.DataFrame, test_size: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sort by date (no shuffling) and take the last `test_size` fraction as
    the held-out test set — a realistic forecast-style evaluation."""
    df_sorted = df.sort_values("date").reset_index(drop=True)
    split_idx = int(len(df_sorted) * (1 - test_size))
    return df_sorted.iloc[:split_idx], df_sorted.iloc[split_idx:]


def build_pipeline(n_estimators: int = 120, max_depth: int = 10, random_state: int = 42) -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )
    model = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=random_state,
        n_jobs=-1,
    )
    return Pipeline(steps=[("preprocess", preprocess), ("model", model)])


def train_and_evaluate(
    df: pd.DataFrame, n_estimators: int = 120, max_depth: int = 10
) -> tuple[Pipeline, dict]:
    """Time-ordered train/test split, fit the pipeline, and compute real
    evaluation metrics on the held-out test set."""
    train_df, test_df = time_ordered_split(df)

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[TARGET_COLUMN]

    pipeline = build_pipeline(n_estimators=n_estimators, max_depth=max_depth)
    pipeline.fit(X_train, y_train)

    predictions = pipeline.predict(X_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, predictions)),
        "rmse": float(root_mean_squared_error(y_test, predictions)),
        "r2": float(r2_score(y_test, predictions)),
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "n_estimators": n_estimators,
        "max_depth": max_depth,
    }
    return pipeline, metrics


def compute_feature_importance(pipeline: Pipeline) -> dict:
    """RandomForest feature importances, with one-hot columns (e.g.
    "district_Lahore", "district_Karachi", ...) aggregated back to their
    parent feature name ("district")."""
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    model: RandomForestRegressor = pipeline.named_steps["model"]

    # transformer name -> list of original input columns it consumed
    parent_columns_by_prefix = {name: cols for name, _, cols in preprocess.transformers_}

    aggregated: dict[str, float] = {}
    for encoded_name, importance in zip(preprocess.get_feature_names_out(), model.feature_importances_):
        prefix, _, rest = encoded_name.partition("__")
        candidates = parent_columns_by_prefix.get(prefix, [])
        parent = next((c for c in candidates if rest == c or rest.startswith(c + "_")), rest)
        aggregated[parent] = aggregated.get(parent, 0.0) + float(importance)

    return dict(sorted(aggregated.items(), key=lambda kv: kv[1], reverse=True))


def compute_global_shap(
    pipeline: Pipeline, df: pd.DataFrame, sample_size: int = GLOBAL_SHAP_SAMPLE_SIZE
) -> dict | None:
    """Real mean(|aggregated SHAP contribution|) per feature (in mm),
    computed on a fixed, seeded random sample of `sample_size` rows from the
    training CSV — so every training run's global_shap.json is
    reproducible. For each sampled row, one-hot SHAP values are aggregated
    back to the 11 parent features (see ml/explain_utils.py) exactly like
    the per-prediction explanation in app/services/explain.py, then the
    absolute value of that per-row aggregated contribution is averaged
    across the sample — the same quantity shown per-prediction, generalized
    to a global average.

    Returns None (NEVER a fabricated stand-in — CLAUDE.md rule 4) if shap
    isn't installed or computing the sample fails for any reason; the caller
    then simply omits global_shap.json rather than writing fake numbers."""
    try:
        import shap
    except Exception:
        logger.warning("shap is not installed — skipping global_shap.json for this training run.")
        return None

    try:
        preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
        model: RandomForestRegressor = pipeline.named_steps["model"]

        sample_n = min(sample_size, len(df))
        sample_df = df.sample(n=sample_n, random_state=GLOBAL_SHAP_SAMPLE_SEED)[FEATURE_COLUMNS]

        Xt = preprocess.transform(sample_df)
        if hasattr(Xt, "toarray"):
            Xt = Xt.toarray()
        Xt = np.asarray(Xt, dtype=np.float64)

        explainer = shap.TreeExplainer(model)
        shap_values = np.asarray(explainer.shap_values(Xt))

        parent_map = build_parent_map(preprocess)
        encoded_names = list(preprocess.get_feature_names_out())

        abs_sum_by_feature = {feature: 0.0 for feature in AGGREGATED_FEATURE_ORDER}
        for row_values in shap_values:
            row_contributions = aggregate_by_parent(row_values, encoded_names, parent_map)
            for feature, contribution in row_contributions.items():
                abs_sum_by_feature[feature] += abs(contribution)

        mean_abs_shap = {feature: total / sample_n for feature, total in abs_sum_by_feature.items()}
        mean_abs_shap = dict(sorted(mean_abs_shap.items(), key=lambda kv: kv[1], reverse=True))

        return {
            "sample_size": sample_n,
            "mean_abs_shap_mm": {k: round(v, 4) for k, v in mean_abs_shap.items()},
        }
    except Exception:
        logger.warning("Computing global SHAP importance failed — skipping global_shap.json.", exc_info=True)
        return None


def save_versioned_model(
    pipeline: Pipeline,
    metrics: dict,
    feature_importance: dict,
    global_shap: dict | None = None,
    model_root: Path = DEFAULT_MODEL_ROOT,
    reference_stats: dict | None = None,
    reference_distribution: dict | None = None,
    extra_registry_fields: dict | None = None,
    set_latest: bool = True,
) -> str:
    """Save model.joblib, metrics.json, feature_importance.json (and
    global_shap.json, when available) under a new
    backend/ml/model/<version>/ directory and update registry.json. Never
    overwrites an existing version directory (microsecond-precision UTC
    timestamps make collisions effectively impossible).

    `reference_stats` (Phase 7, optional): also writes reference_stats.json —
    a per-feature summary of the training data (see ml/pipeline.py's
    compute_reference_stats).
    `reference_distribution` (Phase 8, optional): also writes
    reference_distribution.json — the drift-detection baseline (20-bin
    histograms + summary stats per numeric feature, value frequencies per
    categorical feature — see ml/pipeline.py's compute_reference_distribution)
    consumed by app/services/drift.py's PSI computation.
    `extra_registry_fields` (Phase 7, optional): merged into this version's
    registry.json entry — see ml/registry.py's register_version.
    `set_latest` (Phase 13.1, default True): passed straight through to
    register_version — False records this version fully (artifacts on disk +
    a real registry.json entry) without moving the "latest"/production
    pointer. See ml/pipeline.py's `promote_on_pass`.
    """
    version = "v" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    version_dir = model_root / version
    if version_dir.exists():
        raise FileExistsError(f"Model version directory already exists: {version_dir}")
    version_dir.mkdir(parents=True)

    joblib.dump(pipeline, version_dir / "model.joblib")
    (version_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (version_dir / "feature_importance.json").write_text(json.dumps(feature_importance, indent=2))
    if global_shap is not None:
        (version_dir / "global_shap.json").write_text(json.dumps(global_shap, indent=2))
    if reference_stats is not None:
        (version_dir / "reference_stats.json").write_text(json.dumps(reference_stats, indent=2))
    if reference_distribution is not None:
        (version_dir / "reference_distribution.json").write_text(json.dumps(reference_distribution, indent=2))

    created_at = datetime.now(timezone.utc).isoformat()
    register_version(
        version, metrics, created_at, model_root=model_root, extra=extra_registry_fields, set_latest=set_latest
    )

    return version


def run_training(
    df: pd.DataFrame | None = None,
    data_path: Path | str | None = None,
    model_root: Path = DEFAULT_MODEL_ROOT,
    n_estimators: int = 120,
    max_depth: int = 10,
) -> dict:
    """End-to-end: load data (unless a DataFrame is passed directly), train,
    evaluate, and save a new versioned model. Returns the metrics dict with
    the saved "version" added. Passing `df` directly (e.g. a small sample)
    lets tests run a fast smoke test without touching the real CSV/registry."""
    if df is None:
        path = resolve_data_path() if data_path is None else Path(data_path)
        df = load_dataset(path)

    pipeline, metrics = train_and_evaluate(df, n_estimators=n_estimators, max_depth=max_depth)
    feature_importance = compute_feature_importance(pipeline)
    global_shap = compute_global_shap(pipeline, df)
    version = save_versioned_model(pipeline, metrics, feature_importance, global_shap, model_root=model_root)

    metrics["version"] = version
    return metrics


if __name__ == "__main__":
    result_metrics = run_training()
    print("Training complete.")
    print(json.dumps(result_metrics, indent=2))
