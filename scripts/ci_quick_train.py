"""Phase 11 CI helper — NOT part of the app, only invoked from
.github/workflows/ci.yml.

Model artifacts (backend/ml/model/**/model.joblib, registry.json) ARE
committed to git, so a fresh CI checkout already has a real, servable
production model without this script running at all. This script exists as
an extra end-to-end regression check that the training pipeline machinery
itself (backend/ml/pipeline.py) still runs cleanly on a clean checkout —
using a small deterministic sample + n_estimators=15 so it finishes in
seconds rather than the ~minute a full 78k-row/120-tree run takes, and
skipping MLflow entirely (an unreachable MLFLOW_TRACKING_URI in CI, so
pipeline.py's existing local-file-tracking fallback kicks in automatically
— see docs/MLOPS.md).

A quality-gate FAIL here is EXPECTED and not a problem: a deliberately
tiny/fast candidate will usually score worse than the real production
model (trained on the full dataset with 120 trees), so the gate correctly
refuses to replace a known-good production model with a worse one —
registry.json is simply left untouched, exactly as designed. This script
therefore always exits 0; only a genuine exception (import error, missing
dataset, a crash inside the pipeline) is treated as a real CI failure.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.pipeline import run_pipeline  # noqa: E402
from ml.train_model import load_dataset, resolve_data_path  # noqa: E402

SAMPLE_ROWS = 1500


def main() -> None:
    df = load_dataset(resolve_data_path()).head(SAMPLE_ROWS)
    print(f"[ci_quick_train] Running the training pipeline on a {len(df)}-row sample, n_estimators=15...")

    result = run_pipeline(
        df=df,
        n_estimators=15,
        max_depth=5,
        seed=42,
        # Deliberately unreachable in CI (no MLflow server running) so
        # pipeline.py's existing local-file-tracking fallback is exercised
        # instead of hanging on a real connection attempt.
        tracking_uri="http://127.0.0.1:59999",
    )

    if result["gate_passed"]:
        print(f"[ci_quick_train] Quality gate PASSED — new version {result['version']} registered.")
    else:
        print(
            "[ci_quick_train] Quality gate FAILED (expected for a small/fast CI sample) — "
            f"registry.json left untouched. Reasons: {result['gate_reasons']}"
        )
    print("[ci_quick_train] Pipeline ran end-to-end with no exceptions.")


if __name__ == "__main__":
    main()
