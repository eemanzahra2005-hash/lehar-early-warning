"""Loads the versioned trained model (see ml/train_model.py, ml/registry.py)
and serves predictions built from live request data.

joblib/pandas are deliberately NOT imported at module level (unlike most of
this project's other services) — this module is imported unconditionally by
app/dependencies.py, so a top-level `import pandas` here would force pandas
into memory for every worker process regardless of whether any request ever
actually touches the model (LOW_MEMORY_MODE, Phase 13.1 — see
docs/DEPLOY_RENDER.md). The lazy singleton pattern in app/dependencies.py
already defers *constructing* ModelService until first use; these local
imports make sure the underlying libraries are deferred too."""

import json
import logging
from datetime import date as date_cls
from pathlib import Path

from app.config import get_settings
from ml.feature_schema import FEATURE_COLUMNS
from ml.registry import DEFAULT_MODEL_ROOT, get_latest_version

logger = logging.getLogger("app.ml_model")


class ModelNotAvailableError(Exception):
    """Raised when no trained model version exists in the registry."""


class ModelService:
    """Wraps the versioned RandomForest pipeline. Loaded once as a singleton
    (see app/dependencies.py) — the sklearn Pipeline is read-only at
    inference time, so sharing one instance across requests is safe."""

    def __init__(self, model_root: Path = DEFAULT_MODEL_ROOT, version: str | None = None):
        settings = get_settings()
        requested_version = version if version is not None else settings.model_version
        resolved_version = (
            get_latest_version(model_root) if requested_version == "latest" else requested_version
        )
        if resolved_version is None:
            raise ModelNotAvailableError(
                "No trained model found in the registry. Run "
                "`.venv\\Scripts\\python backend\\ml\\train_model.py` first."
            )

        version_dir = model_root / resolved_version
        pipeline_path = version_dir / "model.joblib"
        if not pipeline_path.exists():
            raise ModelNotAvailableError(f"Model version '{resolved_version}' not found at {version_dir}")

        self.version = resolved_version
        self.model_root = model_root

        import joblib

        # LOW_MEMORY_MODE: memory-map the pickled numpy arrays inside the
        # pipeline (each tree's internal arrays) instead of copying them
        # into the process's own heap — mmap_mode="r" is read-only, which
        # is all inference ever needs. Falls back to a normal load if mmap
        # isn't possible for some reason (e.g. an unsupported/compressed
        # joblib file) rather than failing to serve at all.
        if settings.low_memory_mode:
            try:
                self._pipeline = joblib.load(pipeline_path, mmap_mode="r")
            except Exception:
                logger.warning(
                    "mmap_mode load failed for %s — falling back to a normal joblib.load().",
                    pipeline_path,
                    exc_info=True,
                )
                self._pipeline = joblib.load(pipeline_path)
        else:
            self._pipeline = joblib.load(pipeline_path)

        metrics_path = version_dir / "metrics.json"
        self.metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}

    @property
    def pipeline(self):
        """The fitted sklearn Pipeline (preprocess + model steps). Exposed
        so app/services/explain.py can build a SHAP TreeExplainer on the
        RandomForest inside it without duplicating the loading logic above."""
        return self._pipeline

    def feature_importance(self) -> dict:
        path = self.model_root / self.version / "feature_importance.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def build_feature_row(
        self,
        *,
        temperature_c: float,
        humidity_pct: float,
        rainfall_mm: float,
        evapotranspiration_mm: float,
        canal_flow_cusecs: float,
        soil_moisture_pct: float,
        district: str,
        crop_type: str,
        was_imputed: int = 0,
        on_date: date_cls | None = None,
    ) -> dict:
        """Builds the exact feature row the training pipeline expects
        (month + day_of_year are derived from on_date). Exposed separately
        from predict_row() so callers (e.g. the /predict router) can reuse
        the same row for both the prediction and its SHAP explanation."""
        on_date = on_date or date_cls.today()
        return {
            "district": district,
            "crop_type": crop_type,
            "temperature_c": temperature_c,
            "humidity_pct": humidity_pct,
            "rainfall_mm": rainfall_mm,
            "evapotranspiration_mm": evapotranspiration_mm,
            "canal_flow_cusecs": canal_flow_cusecs,
            "soil_moisture_pct": soil_moisture_pct,
            "was_imputed": was_imputed,
            "month": on_date.month,
            "day_of_year": on_date.timetuple().tm_yday,
        }

    def predict_row(self, row: dict) -> float:
        """Predicts from an already-built feature row (see
        build_feature_row). Returns the raw predicted
        irrigation_recommendation_mm (unclamped, unrounded)."""
        import pandas as pd

        X = pd.DataFrame([row], columns=FEATURE_COLUMNS)
        prediction = self._pipeline.predict(X)[0]
        return float(prediction)

    def predict(
        self,
        *,
        temperature_c: float,
        humidity_pct: float,
        rainfall_mm: float,
        evapotranspiration_mm: float,
        canal_flow_cusecs: float,
        soil_moisture_pct: float,
        district: str,
        crop_type: str,
        was_imputed: int = 0,
        on_date: date_cls | None = None,
    ) -> float:
        """Convenience wrapper: builds the feature row and predicts in one
        call. See build_feature_row()/predict_row() to reuse the row (e.g.
        for a SHAP explanation of the same prediction)."""
        row = self.build_feature_row(
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            rainfall_mm=rainfall_mm,
            evapotranspiration_mm=evapotranspiration_mm,
            canal_flow_cusecs=canal_flow_cusecs,
            soil_moisture_pct=soil_moisture_pct,
            district=district,
            crop_type=crop_type,
            was_imputed=was_imputed,
            on_date=on_date,
        )
        return self.predict_row(row)
