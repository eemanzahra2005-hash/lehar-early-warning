"""Re-run the REAL quality gate over every registered model version (LEHAR Phase 1).

Why this exists: the 512MB deployment pins MODEL_VERSION to a specific
compact version rather than following registry.json's "latest" (see
render.yaml, docs/MEMORY.md). Before pinning one, you want to see — not
assume — that it still clears the absolute gates QG_MAX_MAE/QG_MIN_R2, and
how its real metrics compare with the full model local dev serves.

This reads each version's metrics straight from registry.json and feeds them
through ml/pipeline.py's own quality_gate() — the same function the training
pipeline uses, not a re-implementation — so the verdicts printed here are the
same verdicts training would reach. Nothing is trained, promoted or written:
this script only reads.

    .venv\\Scripts\\python scripts\\check_deployment_models.py

Every number printed is read from a real artifact on disk (CLAUDE.md rule 4 —
never fabricated). All metrics are measured on SYNTHETIC research data
(CLAUDE.md rule 13).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from ml.pipeline import quality_gate  # noqa: E402
from ml.registry import DEFAULT_MODEL_ROOT, read_registry  # noqa: E402

BYTES_PER_MB = 1024 * 1024


def main() -> int:
    settings = get_settings()
    registry = read_registry(DEFAULT_MODEL_ROOT)
    latest = registry.get("latest")

    print("Quality gate re-check over every registered model version")
    print(f"Thresholds: QG_MAX_MAE={settings.qg_max_mae}  QG_MIN_R2={settings.qg_min_r2}")
    print(f"registry.json 'latest' (what local dev serves): {latest}")
    print(f"SHAP cap under LOW_MEMORY_MODE: LOW_MEMORY_SHAP_MAX_ESTIMATORS={settings.low_memory_shap_max_estimators}")
    print()

    for version, entry in registry.get("versions", {}).items():
        metrics = entry.get("metrics", {})
        model_path = DEFAULT_MODEL_ROOT / version / "model.joblib"
        size_mb = model_path.stat().st_size / BYTES_PER_MB if model_path.exists() else None
        n_estimators = metrics.get("n_estimators")

        # compare_to_production=False: these are already-registered versions
        # being judged as deployment candidates, so the absolute ceilings are
        # the relevant test — exactly what promote/rollback applies too (see
        # app/routers/models.py, docs/MLOPS.md).
        gate = quality_gate(metrics, None, settings, compare_to_production=False)

        shap_note = (
            "SHAP kept"
            if n_estimators is not None and n_estimators <= settings.low_memory_shap_max_estimators
            else "SHAP skipped under LOW_MEMORY_MODE"
        )
        print(f"{version}{'   <- latest' if version == latest else ''}")
        print(
            f"  trees={n_estimators} depth={metrics.get('max_depth')} "
            f"n_train={metrics.get('n_train')} n_test={metrics.get('n_test')}"
        )
        print(
            f"  MAE={metrics.get('mae'):.4f}  RMSE={metrics.get('rmse'):.4f}  R2={metrics.get('r2'):.4f}"
            if metrics.get("mae") is not None
            else "  metrics: unavailable"
        )
        print(f"  model.joblib: {size_mb:.1f} MB" if size_mb is not None else "  model.joblib: MISSING")
        print(f"  gate: {'PASS' if gate.passed else 'FAIL'} — {gate.reasons[0]}")
        print(f"  {shap_note}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
