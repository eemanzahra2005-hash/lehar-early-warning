"""GET /api/v1/explain/global — real global feature importance (mean
|SHAP contribution|, in mm) computed offline during training (see
backend/ml/train_model.py's compute_global_shap on a fixed 500-row training
sample) and saved as global_shap.json inside the current model version's
folder (backend/ml/model/<version>/global_shap.json).

Returns available=false — never a fabricated number, per CLAUDE.md rule 4 —
if that file doesn't exist for the currently loaded model version (e.g. shap
wasn't installed at training time; see app/services/explain.py's module
docstring for the same never-fabricate contract on the per-prediction side).
"""

import json

from fastapi import APIRouter, Depends

from app.dependencies import get_model_service
from app.schemas import GlobalExplainResponse
from app.services.ml_model import ModelService

router = APIRouter(prefix="/explain", tags=["explain"])

NOTE = (
    "Mean absolute SHAP contribution (mm) per feature, computed on a fixed 500-row "
    "sample of the training dataset. Describes the RandomForest model's overall "
    "behavior across many predictions — not any single prediction."
)
UNAVAILABLE_NOTE = (
    "Global SHAP importance is not available for the currently loaded model version "
    "(global_shap.json was not produced at training time)."
)


@router.get("/global", response_model=GlobalExplainResponse)
def get_global_explanation(model_service: ModelService = Depends(get_model_service)) -> GlobalExplainResponse:
    path = model_service.model_root / model_service.version / "global_shap.json"
    if not path.exists():
        return GlobalExplainResponse(available=False, note=UNAVAILABLE_NOTE)

    data = json.loads(path.read_text())
    return GlobalExplainResponse(
        available=True,
        model_version=model_service.version,
        sample_size=data["sample_size"],
        mean_abs_shap_mm=data["mean_abs_shap_mm"],
        note=NOTE,
    )
