"""
Staged, MLflow-tracked training pipeline (Phase 7):

    load_data -> validate -> split -> train -> evaluate -> quality_gate
              -> track -> register

This module EXTENDS train_model.py rather than replacing it: it reuses
train_model.py's pipeline-building, time-ordered split, feature-importance,
global-SHAP, and versioned-save helpers, so the on-disk model.joblib format
and backend/ml/model/registry.json — the two things
app/services/ml_model.py depends on to serve predictions — are completely
unchanged (CLAUDE.md rule 1). What this module adds on top:

  - validate(): basic schema + physical-range checks on the dataset before
    training on it (Phase 8 will upgrade this into a real validation/drift
    suite).
  - quality_gate(): compares the candidate against the CURRENT production
    model's metrics (from registry.json) using configurable thresholds
    (QG_MAX_MAE, QG_MAE_TOLERANCE, QG_MIN_R2 — see app/config.py and
    docs/MLOPS.md). A known-good production model is NEVER auto-replaced by
    a worse candidate.
  - MLflow experiment tracking (params/metrics/artifacts/tags) and model
    registry (alias "champion" on promotion), with automatic fallback to
    local file tracking (mlruns/) when the MLflow server is unreachable —
    training must always work fully offline.

Run directly to train a new candidate on the real dataset and (if it passes
the gate) promote it to production:

    .venv\\Scripts\\python backend\\ml\\pipeline.py [--n-estimators N] [--max-depth N] [--seed N]

Or train the COMPACT DEPLOYMENT MODEL (LEHAR Phase 1) — the smaller variant
the 512MB-constrained deployment serves, registered but never promoted over
local dev's production pointer:

    .venv\\Scripts\\python backend\\ml\\pipeline.py --compact

Exit code is 0 when the quality gate PASSES, 1 when it FAILS — safe to call
unattended (e.g. from Task Scheduler/cron; see scripts/retrain.bat|sh and
docs/MLOPS.md).
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — this pipeline never has a display attached
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

# Make `ml` and `app` importable as packages whether this file is run
# directly (`python backend/ml/pipeline.py`) or imported from tests.
ML_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ML_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings, get_settings  # noqa: E402
from ml.registry import DEFAULT_MODEL_ROOT, read_registry  # noqa: E402
from ml.train_model import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_pipeline,
    compute_feature_importance,
    compute_global_shap,
    load_dataset,
    resolve_data_path,
    save_versioned_model,
    time_ordered_split,
)
from ml.validation import DataValidationError, ValidationReport, validate_training_data  # noqa: E402

logger = logging.getLogger("ml.pipeline")

# --- Compact deployment model profile (LEHAR Phase 1) ------------------------
#
# One named profile for "the model the 512MB-constrained deployment serves",
# so the hyperparameters that were actually measured against that ceiling
# live in code rather than in a command someone has to remember correctly
# (docs/MEMORY.md records the measured result of running exactly this).
#
# n_estimators is deliberately <= LOW_MEMORY_SHAP_MAX_ESTIMATORS (app/config.py,
# default 60), so per-prediction SHAP explanations keep working on the
# deployed host instead of degrading to explanation=null. max_depth stays at
# the full model's 10: depth is cheap here compared with tree count, and
# keeping it preserves accuracy the gate then verifies for real.
#
# The profile also implies the two flags a deployment-targeted candidate
# needs, because both follow from what it IS rather than from taste:
#   - compare_to_production=False: it is not trying to beat the full 120-tree
#     local production model on MAE, it is trying to fit in 512MB. It is
#     still held to the absolute QG_MAX_MAE/QG_MIN_R2 gates.
#   - promote_on_pass=False: it must NOT become local dev's "latest". It is
#     selected explicitly by MODEL_VERSION on the host that wants it (see
#     render.yaml, docs/MEMORY.md).
# Both can still be overridden on the command line -- see _parse_args().
COMPACT_N_ESTIMATORS = 60
COMPACT_MAX_DEPTH = 10

MLFLOW_EXPERIMENT_NAME = "irrigation-rf"
MLFLOW_REGISTERED_MODEL_NAME = "irrigation-rf"
MLFLOW_HEALTH_TIMEOUT_SECONDS = 2.0
LOCAL_MLRUNS_DIR = PROJECT_ROOT / "mlruns"


@dataclass
class GateResult:
    """Quality-gate decision. `reasons[0]` is always the headline verdict;
    any further entries are supporting detail — see quality_gate()."""

    passed: bool
    reasons: list[str] = field(default_factory=list)


# --- Stage: validate --------------------------------------------------------

def validate(df: pd.DataFrame) -> ValidationReport:
    """Real pandera schema validation (Phase 8, ml/validation.py) — physical
    range checks, known-district/crop_type checks, and a missing-value
    report, collecting EVERY violation in one pass rather than stopping at
    the first. Raises DataValidationError (a ValueError subclass) if the
    dataset fails — never silently trains on bad data — carrying the full
    ValidationReport for the caller to log/save as an MLflow artifact (see
    run_pipeline() and log_validation_failure_run() below). Returns the
    passing ValidationReport otherwise."""
    report = validate_training_data(df)
    if not report.passed:
        raise DataValidationError(report)
    logger.info(
        "Stage [validate] PASSED: %d rows, %d columns, pandera schema + missing-value/category checks OK.",
        report.n_rows,
        report.n_columns,
    )
    return report


# --- Stage: train / evaluate -------------------------------------------------

def train(train_df: pd.DataFrame, n_estimators: int, max_depth: int, seed: int):
    """Fits the same preprocess+RandomForest pipeline train_model.py builds
    (see build_pipeline), with an explicit, loggable seed."""
    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN]
    pipeline = build_pipeline(n_estimators=n_estimators, max_depth=max_depth, random_state=seed)
    pipeline.fit(X_train, y_train)
    return pipeline


def stratified_sample(df: pd.DataFrame, frac: float, seed: int, group_col: str = "district") -> pd.DataFrame:
    """Phase 13.1: an optional lever for the memory-light deployment model —
    samples `frac` of rows independently WITHIN each district (rather than
    a flat random sample of the whole dataset) so every district stays
    represented in proportion to its own row count, instead of a purely
    random draw risking under-representing (or losing entirely) a
    lower-row-count district. Only ever applied to the TRAIN split (see
    run_pipeline) — the held-out test split stays exactly as-is, so the
    resulting metrics are a fair, apples-to-apples comparison against a
    model trained on the full dataset."""
    return df.groupby(group_col, group_keys=False).sample(frac=frac, random_state=seed)


def evaluate(pipeline, train_df: pd.DataFrame, test_df: pd.DataFrame, n_estimators: int, max_depth: int) -> tuple[dict, np.ndarray]:
    """Real, computed-on-the-held-out-split metrics (CLAUDE.md rule 4 — never
    fabricated). Returns (metrics, predictions) — predictions are reused for
    the residuals plot."""
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[TARGET_COLUMN]
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
    return metrics, predictions


# --- Stage: quality_gate -----------------------------------------------------

def quality_gate(
    candidate: dict, production: dict | None, settings: Settings, compare_to_production: bool = True
) -> GateResult:
    """Compares the candidate's real evaluation metrics against the CURRENT
    production model's (if any). See docs/MLOPS.md for the full decision
    matrix and why these are pragmatic project defaults, not scientific
    constants.

    `compare_to_production=False` (Phase 13.1): skips the tolerance-vs-
    production comparison even when a production model exists — the
    candidate is still held to the two ABSOLUTE floors/ceilings
    (QG_MAX_MAE, QG_MIN_R2), just not judged against production's specific
    MAE. For a candidate that deliberately targets a different deployment
    profile (e.g. the memory-light model trained for LOW_MEMORY_MODE hosts —
    see run_pipeline's `promote_on_pass`), "worse than a much bigger
    production model" is an expected, accepted tradeoff, not a quality
    problem — the absolute floors are what actually guards against shipping
    a broken model.
    """
    reasons: list[str] = []
    passed = True

    if candidate["mae"] > settings.qg_max_mae:
        passed = False
        reasons.append(
            f"Candidate MAE {candidate['mae']:.4f} exceeds the absolute ceiling "
            f"QG_MAX_MAE={settings.qg_max_mae}."
        )

    if candidate["r2"] < settings.qg_min_r2:
        passed = False
        reasons.append(
            f"Candidate R2 {candidate['r2']:.4f} is below the minimum QG_MIN_R2={settings.qg_min_r2}."
        )

    if not compare_to_production:
        reasons.append(
            "Production comparison skipped (compare_to_production=False) — evaluated only against "
            "the absolute ceilings QG_MAX_MAE/QG_MIN_R2, deliberately not against production's MAE "
            "(a different deployment profile, e.g. a memory-light model — see PROGRESS.md Phase 13.1)."
        )
    elif production is not None:
        allowed_mae = production["mae"] + settings.qg_mae_tolerance
        if candidate["mae"] > allowed_mae:
            passed = False
            reasons.append(
                f"Candidate MAE {candidate['mae']:.4f} exceeds production MAE {production['mae']:.4f} "
                f"by more than QG_MAE_TOLERANCE={settings.qg_mae_tolerance} (max allowed {allowed_mae:.4f})."
            )
    else:
        reasons.append("No existing production model — evaluated only against the absolute ceilings.")

    if passed:
        if not compare_to_production or production is None:
            reasons.insert(0, "PASS: candidate meets the absolute ceilings QG_MAX_MAE and QG_MIN_R2.")
        elif candidate["mae"] <= production["mae"]:
            reasons.insert(
                0, f"PASS: candidate MAE {candidate['mae']:.4f} is better than or equal to "
                   f"production MAE {production['mae']:.4f}."
            )
        else:
            reasons.insert(
                0, f"PASS: candidate MAE {candidate['mae']:.4f} is worse than production MAE "
                   f"{production['mae']:.4f} but within QG_MAE_TOLERANCE={settings.qg_mae_tolerance}."
            )
    else:
        reasons.insert(0, "FAIL: candidate rejected — see reasons below.")

    return GateResult(passed=passed, reasons=reasons)


# --- Supporting artifacts -----------------------------------------------------

def compute_reference_stats(df: pd.DataFrame) -> dict:
    """Per-feature summary of the training data — numeric mean/std/min/max,
    categorical value counts. Written as reference_stats.json alongside every
    pipeline-trained model version. Superseded for drift-detection purposes
    by compute_reference_distribution() below (Phase 8), kept as-is for
    backward compatibility since nothing about its existing shape changed."""
    numeric_stats = {
        column: {
            "mean": float(df[column].mean()),
            "std": float(df[column].std()),
            "min": float(df[column].min()),
            "max": float(df[column].max()),
        }
        for column in NUMERIC_FEATURES
    }
    categorical_stats = {column: df[column].value_counts().to_dict() for column in CATEGORICAL_FEATURES}
    return {"n_rows": int(len(df)), "numeric": numeric_stats, "categorical": categorical_stats}


# Phase 8 drift baseline: scoped to the 6 numeric + 2 categorical features
# that are actually logged per prediction (app/db.py's PredictionLog
# columns) — NOT the full training feature set, which also has
# engineering-only columns (was_imputed/month/day_of_year) live traffic
# never reports and drift monitoring has no counterpart for.
DRIFT_NUMERIC_FEATURES = [
    "temperature_c",
    "humidity_pct",
    "rainfall_mm",
    "evapotranspiration_mm",
    "canal_flow_cusecs",
    "soil_moisture_pct",
]
DRIFT_CATEGORICAL_FEATURES = CATEGORICAL_FEATURES  # ["district", "crop_type"] — identical set
REFERENCE_DISTRIBUTION_BINS = 20


def compute_reference_distribution(df: pd.DataFrame, n_bins: int = REFERENCE_DISTRIBUTION_BINS) -> dict:
    """Drift-detection baseline (Phase 8), written as
    reference_distribution.json alongside every pipeline-trained model
    version and read by app/services/drift.py's PSI computation: for each
    numeric feature, a fixed-width `n_bins`-bin histogram (edges + counts)
    plus mean/std/min/max; for each categorical feature, raw value
    frequencies. Computed on the TRAINING split only (never the test split)
    so the baseline reflects exactly what the model was fit on — the same
    df compute_reference_stats() above is called with."""
    numeric = {}
    for column in DRIFT_NUMERIC_FEATURES:
        values = df[column].dropna().to_numpy(dtype=float)
        counts, edges = np.histogram(values, bins=n_bins)
        numeric[column] = {
            "hist_edges": [round(float(edge), 4) for edge in edges],
            "hist_counts": [int(count) for count in counts],
            "mean": float(df[column].mean()),
            "std": float(df[column].std()),
            "min": float(df[column].min()),
            "max": float(df[column].max()),
        }
    categorical = {column: df[column].value_counts().to_dict() for column in DRIFT_CATEGORICAL_FEATURES}
    return {"n_rows": int(len(df)), "n_bins": n_bins, "numeric": numeric, "categorical": categorical}


def compute_dataset_hash(path: Path | None, df: pd.DataFrame) -> str:
    """SHA-256 (first 16 hex chars) of the dataset file's bytes, or of the
    DataFrame's content when there's no backing file (e.g. an in-memory
    sample passed directly to run_pipeline() in tests)."""
    if path is not None and path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    row_hashes = pd.util.hash_pandas_object(df, index=True).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:16]


def resolve_git_commit() -> str | None:
    """Best-effort short git commit hash for the current HEAD. Returns None
    (never raises) outside a git checkout or if git isn't installed."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        logger.debug("git commit hash unavailable", exc_info=True)
    return None


def plot_residuals(y_true: np.ndarray, y_pred: np.ndarray, out_path: Path) -> None:
    """Residuals-vs-predicted scatter (matplotlib Agg, no display needed) —
    a real diagnostic plot from the actual held-out test split, logged as an
    MLflow artifact for human review, never a placeholder image."""
    residuals = np.asarray(y_true) - np.asarray(y_pred)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(y_pred, residuals, alpha=0.3, s=8, edgecolors="none")
    ax.axhline(0, color="red", linewidth=1, linestyle="--")
    ax.set_xlabel("Predicted irrigation_recommendation_mm")
    ax.set_ylabel("Residual (actual - predicted)")
    ax.set_title("Residuals vs predicted (held-out test split)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


# --- Stage: track (MLflow) ---------------------------------------------------

def mlflow_server_reachable(tracking_uri: str) -> bool:
    if not tracking_uri.startswith("http"):
        return False
    try:
        import requests

        response = requests.get(f"{tracking_uri.rstrip('/')}/health", timeout=MLFLOW_HEALTH_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def configure_mlflow(tracking_uri: str, mlruns_dir: Path) -> tuple[str, bool]:
    """Returns (effective_tracking_uri, using_remote_server). Falls back to
    local file tracking when the configured MLflow server can't be reached —
    training must work fully offline (Phase 7 brief)."""
    import mlflow

    if mlflow_server_reachable(tracking_uri):
        mlflow.set_tracking_uri(tracking_uri)
        return tracking_uri, True

    logger.warning(
        "MLflow server at %s is unreachable — falling back to local file tracking at %s "
        "(start the real server with `docker compose up -d mlflow` to use shared tracking + the "
        "model registry).",
        tracking_uri,
        mlruns_dir,
    )
    mlruns_dir.mkdir(parents=True, exist_ok=True)
    # MLflow 3.x puts the bare filesystem tracking store into "maintenance
    # mode" (raises unless explicitly opted into) since it lacks the model
    # registry and newer features — but it's still fully supported for
    # tracking, and is exactly the offline fallback this pipeline needs.
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    local_uri = mlruns_dir.resolve().as_uri()
    mlflow.set_tracking_uri(local_uri)
    return local_uri, False


def log_validation_failure_run(
    *,
    report: ValidationReport,
    dataset_path: Path,
    dataset_hash: str,
    tracking_uri: str,
    mlruns_dir: Path,
) -> dict:
    """Logs a standalone MLflow run recording a FAILED validate() stage.
    Training never runs when validation fails (CLAUDE.md rule 4 — never
    train on data that fails schema), so this is the ONLY MLflow record of
    the attempt — mirrors track_run()'s "always logs to MLflow regardless
    of outcome" contract from Phase 7, extended to cover the validate stage
    too. Deliberately lightweight: no metrics/model/registry, since none of
    those exist yet at this point in the pipeline."""
    import mlflow

    effective_uri, using_remote = configure_mlflow(tracking_uri, mlruns_dir)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    git_commit = resolve_git_commit()

    with mlflow.start_run() as run:
        run_id = run.info.run_id
        mlflow.log_params(
            {
                "dataset_path": str(dataset_path),
                "dataset_row_count": report.n_rows,
                "dataset_file_hash": dataset_hash,
            }
        )
        tags = {"quality_gate": "not_run", "validation": "fail"}
        if git_commit:
            tags["git_commit"] = git_commit
        mlflow.set_tags(tags)

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "validation_report.json"
            report_path.write_text(json.dumps(report.to_dict(), indent=2))
            mlflow.log_artifact(str(report_path))

    logger.info(
        "Stage [validate] FAILED — logged to MLflow run_id=%s (%s) for audit; see validation_report.json.",
        run_id,
        effective_uri,
    )
    return {"run_id": run_id, "tracking_uri": effective_uri, "using_remote_mlflow": using_remote}


def track_run(
    *,
    pipeline,
    metrics: dict,
    feature_importance: dict,
    global_shap: dict | None,
    reference_stats: dict,
    reference_distribution: dict,
    validation_report: dict,
    test_df: pd.DataFrame,
    predictions: np.ndarray,
    dataset_path: Path,
    dataset_hash: str,
    n_estimators: int,
    max_depth: int,
    seed: int,
    gate: GateResult,
    tracking_uri: str,
    mlruns_dir: Path,
) -> dict:
    """Logs one MLflow run: params, metrics, artifacts, tags — always, PASS
    or FAIL, so a rejected candidate is still auditable. Registers the model
    (alias "champion") ONLY when the gate passed, and only best-effort: the
    local file-tracking fallback doesn't support the model registry, so that
    failure is caught and logged, never allowed to break the pipeline."""
    import mlflow

    effective_uri, using_remote = configure_mlflow(tracking_uri, mlruns_dir)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    git_commit = resolve_git_commit()

    with mlflow.start_run() as run:
        run_id = run.info.run_id

        mlflow.log_params(
            {
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "seed": seed,
                "feature_list": ",".join(FEATURE_COLUMNS),
                "dataset_path": str(dataset_path),
                "dataset_row_count": metrics["n_train"] + metrics["n_test"],
                "dataset_file_hash": dataset_hash,
            }
        )
        mlflow.log_metrics(
            {
                "mae": metrics["mae"],
                "rmse": metrics["rmse"],
                "r2": metrics["r2"],
                "n_train": metrics["n_train"],
                "n_test": metrics["n_test"],
            }
        )
        tags = {"quality_gate": "pass" if gate.passed else "fail"}
        if git_commit:
            tags["git_commit"] = git_commit
        mlflow.set_tags(tags)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "feature_importance.json").write_text(json.dumps(feature_importance, indent=2))
            mlflow.log_artifact(str(tmp_dir / "feature_importance.json"))

            if global_shap is not None:
                (tmp_dir / "global_shap.json").write_text(json.dumps(global_shap, indent=2))
                mlflow.log_artifact(str(tmp_dir / "global_shap.json"))

            (tmp_dir / "reference_stats.json").write_text(json.dumps(reference_stats, indent=2))
            mlflow.log_artifact(str(tmp_dir / "reference_stats.json"))

            (tmp_dir / "reference_distribution.json").write_text(json.dumps(reference_distribution, indent=2))
            mlflow.log_artifact(str(tmp_dir / "reference_distribution.json"))

            (tmp_dir / "validation_report.json").write_text(json.dumps(validation_report, indent=2))
            mlflow.log_artifact(str(tmp_dir / "validation_report.json"))

            residuals_path = tmp_dir / "residuals.png"
            plot_residuals(test_df[TARGET_COLUMN].to_numpy(), predictions, residuals_path)
            mlflow.log_artifact(str(residuals_path))

        try:
            import mlflow.sklearn

            mlflow.sklearn.log_model(pipeline, name="model")
        except Exception:
            logger.warning("Failed to log the model artifact to MLflow — run metadata was still recorded.", exc_info=True)

        registered_version = None
        if gate.passed:
            try:
                mv = mlflow.register_model(model_uri=f"runs:/{run_id}/model", name=MLFLOW_REGISTERED_MODEL_NAME)
                mlflow.MlflowClient().set_registered_model_alias(MLFLOW_REGISTERED_MODEL_NAME, "champion", mv.version)
                registered_version = mv.version
                logger.info(
                    "MLflow: registered '%s' version %s and set alias 'champion'.",
                    MLFLOW_REGISTERED_MODEL_NAME,
                    mv.version,
                )
            except Exception:
                logger.warning(
                    "MLflow model registry unavailable (expected when running against the local "
                    "file-tracking fallback, which doesn't support the registry) — skipping "
                    "registration/alias. The local registry.json dual-write below still applies.",
                    exc_info=True,
                )

    return {
        "run_id": run_id,
        "tracking_uri": effective_uri,
        "using_remote_mlflow": using_remote,
        "mlflow_model_version": registered_version,
    }


# --- Stage: register (local dual-write) --------------------------------------

def register_locally(
    *,
    pipeline,
    metrics: dict,
    feature_importance: dict,
    global_shap: dict | None,
    reference_stats: dict,
    reference_distribution: dict,
    model_root: Path,
    extra_registry_fields: dict,
    set_latest: bool = True,
) -> str:
    """Saves the versioned artifact folder (same format ModelService already
    reads) and, by default, updates registry.json's "latest" pointer — the
    dual-write that keeps the existing API working unchanged. ONLY called
    when the quality gate passes.

    `set_latest=False` (Phase 13.1): still writes the full versioned
    artifact folder + a real registry.json entry, but leaves "latest"
    (the local production pointer) untouched — see run_pipeline's
    `promote_on_pass`.
    """
    return save_versioned_model(
        pipeline,
        metrics,
        feature_importance,
        global_shap,
        model_root=model_root,
        reference_stats=reference_stats,
        reference_distribution=reference_distribution,
        extra_registry_fields=extra_registry_fields,
        set_latest=set_latest,
    )


# --- Orchestrator -------------------------------------------------------------

def run_pipeline(
    *,
    df: pd.DataFrame | None = None,
    data_path: Path | str | None = None,
    model_root: Path = DEFAULT_MODEL_ROOT,
    n_estimators: int = 120,
    max_depth: int = 10,
    seed: int = 42,
    sample_frac: float | None = None,
    compare_to_production: bool = True,
    promote_on_pass: bool = True,
    tracking_uri: str | None = None,
    mlruns_dir: Path | None = None,
    settings: Settings | None = None,
) -> dict:
    """End-to-end: load -> validate -> split -> train -> evaluate ->
    quality_gate -> track -> register. Passing `df` directly (e.g. a small
    sample) and/or an explicit `tracking_uri`/`mlruns_dir`/`settings` lets
    tests run a fast, fully offline smoke test — including forcing a
    quality-gate FAIL via a custom `settings` — without touching the real
    dataset, registry, or MLflow server.

    `sample_frac` (Phase 13.1, optional): stratified-by-district sample of
    the TRAIN split only (see stratified_sample) — the held-out test split
    is always evaluated in full, so metrics stay a fair, apples-to-apples
    comparison. Used for the memory-light deployment model variant.
    `compare_to_production` (Phase 13.1, default True): passed straight
    through to quality_gate — set False for a candidate that isn't trying
    to beat production on accuracy (see quality_gate's docstring).
    `promote_on_pass` (Phase 13.1, default True): whether a PASSing
    candidate becomes the new "latest"/production pointer. False still
    writes the full versioned artifact + registry.json entry (register_locally's
    `set_latest=False`) — a normal, real registry version that just isn't
    served locally by default.
    """
    settings = settings if settings is not None else get_settings()
    resolved_tracking_uri = tracking_uri if tracking_uri is not None else settings.mlflow_tracking_uri
    resolved_mlruns_dir = mlruns_dir if mlruns_dir is not None else LOCAL_MLRUNS_DIR

    if df is None:
        path = resolve_data_path() if data_path is None else Path(data_path)
        logger.info("Stage [load_data]: %s", path)
        df = load_dataset(path)
        dataset_path: Path | None = path
    else:
        dataset_path = Path(data_path) if data_path is not None else None
    logger.info("Stage [load_data] done: %d rows.", len(df))
    dataset_hash = compute_dataset_hash(dataset_path, df)

    try:
        validation_report = validate(df)
    except DataValidationError as exc:
        logger.error("Stage [validate] FAILED: %s", exc)
        try:
            log_validation_failure_run(
                report=exc.report,
                dataset_path=dataset_path if dataset_path is not None else Path("<in-memory>"),
                dataset_hash=dataset_hash,
                tracking_uri=resolved_tracking_uri,
                mlruns_dir=resolved_mlruns_dir,
            )
        except Exception:
            logger.warning(
                "Failed to log the validation-failure run to MLflow — the run is still failing as expected.",
                exc_info=True,
            )
        raise

    train_df, test_df = time_ordered_split(df)
    logger.info("Stage [split] done: %d train rows, %d test rows.", len(train_df), len(test_df))

    if sample_frac is not None:
        pre_sample_n = len(train_df)
        train_df = stratified_sample(train_df, frac=sample_frac, seed=seed)
        logger.info(
            "Stage [split] sample_frac=%.3f applied to the TRAIN split only: %d -> %d rows "
            "(test split unchanged at %d rows, for a fair metrics comparison).",
            sample_frac, pre_sample_n, len(train_df), len(test_df),
        )

    logger.info("Stage [train]: n_estimators=%d max_depth=%d seed=%d", n_estimators, max_depth, seed)
    pipeline = train(train_df, n_estimators=n_estimators, max_depth=max_depth, seed=seed)
    logger.info("Stage [train] done.")

    metrics, predictions = evaluate(pipeline, train_df, test_df, n_estimators=n_estimators, max_depth=max_depth)
    logger.info(
        "Stage [evaluate] done: MAE=%.4f RMSE=%.4f R2=%.4f", metrics["mae"], metrics["rmse"], metrics["r2"]
    )

    registry = read_registry(model_root)
    production_version = registry.get("latest")
    production_entry = registry.get("versions", {}).get(production_version) if production_version else None
    production_metrics = production_entry.get("metrics") if production_entry else None

    gate = quality_gate(metrics, production_metrics, settings, compare_to_production=compare_to_production)
    for reason in gate.reasons:
        (logger.info if gate.passed else logger.warning)("Stage [quality_gate] %s", reason)

    feature_importance = compute_feature_importance(pipeline)
    global_shap = compute_global_shap(pipeline, df)
    reference_stats = compute_reference_stats(train_df)
    reference_distribution = compute_reference_distribution(train_df)

    logger.info("Stage [track]: logging run to MLflow.")
    track_result = track_run(
        pipeline=pipeline,
        metrics=metrics,
        feature_importance=feature_importance,
        global_shap=global_shap,
        reference_stats=reference_stats,
        reference_distribution=reference_distribution,
        validation_report=validation_report.to_dict(),
        test_df=test_df,
        predictions=predictions,
        dataset_path=dataset_path if dataset_path is not None else Path("<in-memory>"),
        dataset_hash=dataset_hash,
        n_estimators=n_estimators,
        max_depth=max_depth,
        seed=seed,
        gate=gate,
        tracking_uri=resolved_tracking_uri,
        mlruns_dir=resolved_mlruns_dir,
    )
    logger.info(
        "Stage [track] done: run_id=%s tracking_uri=%s (%s)",
        track_result["run_id"],
        track_result["tracking_uri"],
        "remote MLflow server" if track_result["using_remote_mlflow"] else "local file fallback",
    )

    result = {
        "metrics": metrics,
        "gate_passed": gate.passed,
        "gate_reasons": gate.reasons,
        "mlflow_run_id": track_result["run_id"],
        "mlflow_tracking_uri": track_result["tracking_uri"],
        "mlflow_using_remote": track_result["using_remote_mlflow"],
        "mlflow_model_version": track_result["mlflow_model_version"],
        "version": None,
    }

    if gate.passed:
        extra_fields = {
            "source": "pipeline",
            "seed": seed,
            "sample_frac": sample_frac,
            "dataset_path": str(dataset_path) if dataset_path is not None else None,
            "dataset_hash": dataset_hash,
            "mlflow_run_id": track_result["run_id"],
            "mlflow_tracking_uri": track_result["tracking_uri"],
            "mlflow_model_version": (
                str(track_result["mlflow_model_version"]) if track_result["mlflow_model_version"] is not None else None
            ),
            "gate": {"passed": True, "reasons": gate.reasons, "compared_to_production": compare_to_production},
        }
        version = register_locally(
            pipeline=pipeline,
            metrics=metrics,
            feature_importance=feature_importance,
            global_shap=global_shap,
            reference_stats=reference_stats,
            reference_distribution=reference_distribution,
            model_root=model_root,
            extra_registry_fields=extra_fields,
            set_latest=promote_on_pass,
        )
        result["version"] = version
        if promote_on_pass:
            logger.info("Stage [register] done: new production version %s (registry.json 'latest' updated).", version)
        else:
            logger.info(
                "Stage [register] done: version %s saved to registry.json WITHOUT promoting it — "
                "the current production pointer is untouched (promote_on_pass=False).",
                version,
            )
    else:
        logger.warning(
            "Stage [register] SKIPPED — quality gate FAILED. registry.json is untouched; "
            "the current production model remains active. See gate_reasons above."
        )
        # LEHAR Phase 2: leave a breadcrumb the alert engine's OPS rule can
        # pick up on its next run. This pipeline runs in its own process
        # (no API database session), which is exactly why ops_events is a
        # small file rather than a table — see
        # app/services/alerts/ops_events.py. Best-effort: it never raises,
        # so a failed gate is still reported normally even if the write
        # fails. The import is local so the training pipeline's module-level
        # import graph is unchanged.
        from app.services.alerts.ops_events import record_ops_event

        headline = gate.reasons[0] if gate.reasons else "no reason recorded"
        record_ops_event("quality_gate_fail", f"Quality gate FAILED: {headline}")

    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    # Default None (not the literal 120/10) so --compact can tell "the user
    # asked for this value" apart from "the user said nothing" — see
    # _apply_compact_profile below, which fills in whichever profile applies.
    parser.add_argument("--n-estimators", type=int, default=None)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    # LEHAR Phase 1 — the compact deployment model (see the COMPACT_*
    # constants at the top of this module for what it sets and why).
    parser.add_argument(
        "--compact",
        action="store_true",
        help=(
            f"Train the compact deployment model for a 512MB host: n_estimators="
            f"{COMPACT_N_ESTIMATORS}, max_depth={COMPACT_MAX_DEPTH}, gated against the absolute "
            "ceilings only, registered WITHOUT moving the 'latest' pointer. Select it at runtime "
            "with MODEL_VERSION=<the printed version> (see docs/MEMORY.md). An explicit "
            "--n-estimators/--max-depth/--sample-frac still wins over the profile's value."
        ),
    )
    # Phase 13.1 — memory-light deployment model variant (see
    # docs/DEPLOY_RENDER.md, PROGRESS.md Phase 13.1):
    parser.add_argument(
        "--sample-frac",
        type=float,
        default=None,
        help="Stratified-by-district sample of the TRAIN split only (0-1]; test split always stays full.",
    )
    parser.add_argument(
        "--no-compare-production",
        dest="compare_to_production",
        action="store_false",
        help="Skip the tolerance-vs-production MAE comparison; still held to QG_MAX_MAE/QG_MIN_R2.",
    )
    parser.add_argument(
        "--no-promote",
        dest="promote_on_pass",
        action="store_false",
        help="Save a PASSing candidate as a normal registry version WITHOUT moving the 'latest' pointer.",
    )
    parser.set_defaults(compare_to_production=None, promote_on_pass=None)
    return _apply_compact_profile(parser.parse_args())


# Defaults for a normal (non-compact) run — unchanged from every phase before
# LEHAR Phase 1: the full 120-tree model, gated against production, promoted
# on pass. Named here only so _apply_compact_profile can express "fall back to
# what this script always did" in one place.
DEFAULT_N_ESTIMATORS = 120
DEFAULT_MAX_DEPTH = 10


def _apply_compact_profile(args: argparse.Namespace) -> argparse.Namespace:
    """Resolves the still-unset options, so an explicit flag ALWAYS wins over
    the profile it would otherwise come from (e.g. `--compact --n-estimators
    40`, or `--compact` plus an explicit choice to promote). Returns the same
    namespace, mutated, with every field non-None."""
    if args.compact:
        if args.n_estimators is None:
            args.n_estimators = COMPACT_N_ESTIMATORS
        if args.max_depth is None:
            args.max_depth = COMPACT_MAX_DEPTH
        if args.compare_to_production is None:
            args.compare_to_production = False
        if args.promote_on_pass is None:
            args.promote_on_pass = False

    if args.n_estimators is None:
        args.n_estimators = DEFAULT_N_ESTIMATORS
    if args.max_depth is None:
        args.max_depth = DEFAULT_MAX_DEPTH
    if args.compare_to_production is None:
        args.compare_to_production = True
    if args.promote_on_pass is None:
        args.promote_on_pass = True
    return args


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    run_result = run_pipeline(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        seed=args.seed,
        sample_frac=args.sample_frac,
        compare_to_production=args.compare_to_production,
        promote_on_pass=args.promote_on_pass,
    )

    print(json.dumps({k: v for k, v in run_result.items() if k != "gate_reasons"}, indent=2))
    print("\nQuality gate reasons:")
    for line in run_result["gate_reasons"]:
        print(f"  - {line}")

    if run_result["gate_passed"]:
        if args.promote_on_pass:
            print(f"\nQuality gate PASSED. New production version: {run_result['version']}")
        else:
            print(f"\nQuality gate PASSED. Version {run_result['version']} saved WITHOUT promoting.")
            if args.compact:
                print(
                    "This is the COMPACT DEPLOYMENT MODEL. Serve it by setting\n"
                    f"    MODEL_VERSION={run_result['version']}\n"
                    "in the deployed environment (render.yaml / backend/.env). registry.json's "
                    "'latest' pointer is untouched, so local dev keeps serving the full model. "
                    "See docs/MEMORY.md."
                )
        sys.exit(0)
    else:
        print("\nQuality gate FAILED. No changes made to registry.json.")
        sys.exit(1)
