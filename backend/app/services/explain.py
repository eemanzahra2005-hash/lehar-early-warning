"""Real per-prediction explainability (Phase 6): a SHAP TreeExplainer built
directly on the RandomForest inside the trained sklearn Pipeline (see
ml/train_model.py), with one-hot-encoded SHAP values aggregated back to the
11 original model input features (see ml/explain_utils.py).

HARD RULE (CLAUDE.md rule 4 / Phase 6 brief): SHAP values are NEVER
fabricated. If the explainer fails to build, or fails on a specific row,
explain()/confidence() return None rather than any invented substitute — the
caller (app/routers/predict.py) sets PredictResponse.explanation/confidence
to null. POST /api/v1/predict must never break because explainability broke.

The TreeExplainer is built ONCE per process (at ExplainService construction
— a singleton via app/dependencies.py's get_explain_service) and reused for
every request, since the underlying trees never change between requests.

numpy/pandas are deliberately NOT imported at module level (Phase 13.1,
LOW_MEMORY_MODE — see docs/DEPLOY_RENDER.md): this module is imported
unconditionally by app/dependencies.py, so a top-level `import numpy`/
`import pandas` here would force both into every worker process regardless
of whether a request ever actually needs an explanation. `import shap` was
already local to __init__ before this phase (an optional runtime dependency)
— see LOW_MEMORY_SHAP_MAX_ESTIMATORS below for the other RAM-vs-explainability
tradeoff this phase adds.
"""

import logging

from app.config import get_settings
from ml.explain_utils import aggregate_by_parent, build_parent_map
from ml.feature_schema import FEATURE_COLUMNS

logger = logging.getLogger("app.explain")

# Human-readable labels for each aggregated feature, applied to the row's
# real input value — never an invented number, just phrasing.
_FEATURE_LABELS = {
    "soil_moisture_pct": lambda v: f"soil moisture ({v:.0f}%)",
    "evapotranspiration_mm": lambda v: f"evapotranspiration ({v:.1f} mm)",
    "rainfall_mm": lambda v: f"rainfall ({v:.1f} mm)",
    "temperature_c": lambda v: f"temperature ({v:.1f}°C)",
    "humidity_pct": lambda v: f"humidity ({v:.0f}%)",
    "canal_flow_cusecs": lambda v: f"canal flow ({v:.0f} cusecs)",
    "district": lambda v: f"district ({v})",
    "crop_type": lambda v: f"crop type ({v})",
    "month": lambda v: f"month ({int(v)})",
    "day_of_year": lambda v: f"day of year ({int(v)})",
    "was_imputed": lambda v: "imputed/estimated weather data" if v else "directly measured weather data",
}

# Qualifier words used only to phrase top_factors sentences ("Low soil
# moisture (18%)..."), applied to the row's real value — fixed thresholds,
# same style as the frontend's rule-based context line (frontend/js/rules.js).
# Never invented data: the adjective changes, the number underneath doesn't.
_QUALIFIERS = {
    "soil_moisture_pct": lambda v: "Low" if v < 30 else ("High" if v > 65 else "Moderate"),
    "evapotranspiration_mm": lambda v: "High" if v > 7 else ("Low" if v < 4 else "Moderate"),
    "rainfall_mm": lambda v: "Low" if v < 2 else ("Heavy" if v > 8 else "Moderate"),
    "temperature_c": lambda v: "Hot" if v > 35 else ("Cool" if v < 15 else "Moderate"),
    "humidity_pct": lambda v: "Dry" if v < 30 else ("Humid" if v > 60 else "Moderate"),
    "canal_flow_cusecs": lambda v: "Low" if v < 150 else ("High" if v > 400 else "Moderate"),
}

# Contributions smaller than this (in mm) are treated as noise and skipped
# when picking top_factors sentences.
_MIN_SENTENCE_CONTRIBUTION_MM = 0.05


def _sentence(feature: str, value, contribution_mm: float) -> str:
    label_fn = _FEATURE_LABELS.get(feature, lambda v: f"{feature} ({v})")
    label = label_fn(value)
    qualifier = _QUALIFIERS.get(feature)
    if qualifier is not None:
        label = f"{qualifier(value)} {label}"
    verb = "increased" if contribution_mm > 0 else "decreased"
    sentence = f"{label} {verb} the recommendation by {abs(contribution_mm):.1f} mm."
    return sentence[0].upper() + sentence[1:]


class ExplainService:
    """Wraps one ModelService's fitted pipeline with a SHAP TreeExplainer.
    See module docstring for the never-fabricate contract."""

    def __init__(self, model_service):
        self._pipeline = model_service.pipeline
        self._preprocess = self._pipeline.named_steps["preprocess"]
        self._model = self._pipeline.named_steps["model"]
        self._parent_map = build_parent_map(self._preprocess)
        self._encoded_names = list(self._preprocess.get_feature_names_out())

        self._explainer = None

        settings = get_settings()
        n_estimators = getattr(self._model, "n_estimators", None)
        if (
            settings.low_memory_mode
            and n_estimators is not None
            and n_estimators > settings.low_memory_shap_max_estimators
        ):
            # LOW_MEMORY_MODE cap (Phase 13.1): this model is bigger than
            # LOW_MEMORY_SHAP_MAX_ESTIMATORS trees — skip building the
            # explainer at all rather than risk the numba JIT warm-up's
            # extra RSS on a RAM-constrained host. Degrades exactly like any
            # other explainer failure: explanation=null, never fabricated.
            # confidence() is UNAFFECTED — it reads self._model.estimators_
            # directly, not the SHAP explainer.
            logger.info(
                "LOW_MEMORY_MODE: skipping SHAP TreeExplainer build — model has %d estimators, "
                "over LOW_MEMORY_SHAP_MAX_ESTIMATORS=%d. explanation will be null for this model "
                "version; confidence (tree-agreement interval) is unaffected.",
                n_estimators,
                settings.low_memory_shap_max_estimators,
            )
            return

        try:
            import shap  # local import: keeps shap an optional runtime dependency

            self._explainer = shap.TreeExplainer(self._model)
            if not settings.low_memory_mode:
                # Eager warm-up only when boot-time memory isn't a concern —
                # under LOW_MEMORY_MODE the first real request pays this
                # cost instead (see app/main.py's lifespan), so there's no
                # value paying it twice.
                self._warm_up()
        except Exception:
            logger.warning(
                "SHAP TreeExplainer could not be built — per-prediction explanations "
                "will be unavailable (explanation=null) until this is resolved.",
                exc_info=True,
            )

    def _warm_up(self) -> None:
        """SHAP's underlying tree-traversal kernel is numba-JIT-compiled on
        its FIRST call, measured locally at ~49s (one-time per process,
        never disk-cached by numba across runs) vs ~0.1s for every call
        after. Paying that cost here, during service construction (wired to
        run at app startup — see app/main.py's lifespan), means the first
        real /predict request a user makes is fast, instead of that user
        being the one who waits ~49s."""
        try:
            import numpy as np

            dummy_row = np.zeros((1, len(self._encoded_names)), dtype=np.float64)
            self._explainer.shap_values(dummy_row)
        except Exception:
            logger.warning("SHAP warm-up call failed — the first real prediction may be slow.", exc_info=True)

    @property
    def available(self) -> bool:
        return self._explainer is not None

    def _transform(self, row: dict):
        import numpy as np
        import pandas as pd

        X = pd.DataFrame([row], columns=FEATURE_COLUMNS)
        Xt = self._preprocess.transform(X)
        if hasattr(Xt, "toarray"):
            Xt = Xt.toarray()
        return np.asarray(Xt, dtype=np.float64)

    def explain(self, row: dict) -> dict | None:
        """`row` must have exactly the keys ModelService.build_feature_row
        produces. Returns None on ANY failure (explainer never built, SHAP
        call raises, ...) — never raises itself."""
        if self._explainer is None:
            return None
        try:
            import numpy as np

            Xt = self._transform(row)
            shap_row = np.asarray(self._explainer.shap_values(Xt))[0]
            base_value = float(np.asarray(self._explainer.expected_value).reshape(-1)[0])

            contributions_by_feature = aggregate_by_parent(shap_row, self._encoded_names, self._parent_map)

            contributions = [
                {
                    "feature": feature,
                    "value": row[feature],
                    "contribution_mm": round(contribution_mm, 3),
                    "direction": "increases" if contribution_mm > 0 else "decreases",
                }
                for feature, contribution_mm in contributions_by_feature.items()
            ]
            contributions.sort(key=lambda c: abs(c["contribution_mm"]), reverse=True)

            top_factors = [
                _sentence(c["feature"], c["value"], c["contribution_mm"])
                for c in contributions
                if abs(c["contribution_mm"]) >= _MIN_SENTENCE_CONTRIBUTION_MM
            ][:4]
            if len(top_factors) < 2:
                # Degenerate/tiny-contribution row: still surface the two
                # largest factors rather than an empty explanation.
                top_factors = [_sentence(c["feature"], c["value"], c["contribution_mm"]) for c in contributions[:2]]

            return {
                "base_value_mm": round(base_value, 3),
                "contributions": contributions,
                "top_factors": top_factors,
            }
        except Exception:
            logger.warning("SHAP explanation failed for a /predict row", exc_info=True)
            return None

    def confidence(self, row: dict) -> dict | None:
        """"Model agreement interval" — spread across the RandomForest's
        individual trees' predictions for this row. NOT a calibrated
        statistical confidence interval, just how much the trees agree.
        Independent of the SHAP explainer (works even if that failed to
        build), so it degrades separately. Returns None on any failure."""
        try:
            import numpy as np

            Xt = self._transform(row)
            tree_predictions = np.array([tree.predict(Xt)[0] for tree in self._model.estimators_])
            std = float(tree_predictions.std())
            p10 = float(np.percentile(tree_predictions, 10))
            p90 = float(np.percentile(tree_predictions, 90))
            return {
                "tree_std_mm": round(std, 3),
                "interval_mm": [round(max(0.0, p10), 1), round(max(0.0, p90), 1)],
            }
        except Exception:
            logger.warning("Confidence interval computation failed for a /predict row", exc_info=True)
            return None
