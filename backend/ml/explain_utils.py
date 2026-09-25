"""Shared helpers for aggregating one-hot-encoded model columns back to their
original parent feature names (e.g. "cat__district_Lahore",
"cat__district_Karachi", ... -> "district").

Used by both the real-time explain service (app/services/explain.py, which
aggregates per-prediction SHAP values) and the offline global-importance
step (train_model.py's compute_global_shap, which aggregates mean |SHAP|
over a training sample) so both surfaces are backed by the exact same
mapping logic. Mirrors the aggregation already used for RandomForest
feature_importances_ in train_model.py's compute_feature_importance.

The `ColumnTransformer` import below is TYPE_CHECKING-only (never executed at
runtime): app/services/explain.py imports this module unconditionally at
serving time, and by the time it's actually called the caller already holds
a real, already-unpickled ColumnTransformer instance (loaded via
app/services/ml_model.py's joblib.load()) — sklearn doesn't need to be
imported a second time here just to type-hint a parameter. Keeps this
module's own import from forcing sklearn into a LOW_MEMORY_MODE worker that
never ends up touching the model (Phase 13.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sklearn.compose import ColumnTransformer

# The 11 features the user sees, in a fixed display order. Matches
# train_model.py's FEATURE_COLUMNS (CATEGORICAL_FEATURES + NUMERIC_FEATURES).
AGGREGATED_FEATURE_ORDER = [
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
]


def build_parent_map(preprocess: ColumnTransformer) -> dict[str, str]:
    """encoded output column name -> parent input feature name, e.g.
    "cat__district_Lahore" -> "district", "num__soil_moisture_pct" ->
    "soil_moisture_pct"."""
    parent_columns_by_prefix = {name: cols for name, _, cols in preprocess.transformers_}
    mapping = {}
    for encoded_name in preprocess.get_feature_names_out():
        prefix, _, rest = encoded_name.partition("__")
        candidates = parent_columns_by_prefix.get(prefix, [])
        parent = next((c for c in candidates if rest == c or rest.startswith(c + "_")), rest)
        mapping[encoded_name] = parent
    return mapping


def aggregate_by_parent(values, encoded_names, parent_map: dict[str, str]) -> dict[str, float]:
    """Sums a 1D sequence of per-encoded-column values (SHAP values for one
    row) back to their parent feature names. Always returns exactly the 11
    keys in AGGREGATED_FEATURE_ORDER, even if a feature's net contribution
    is zero."""
    aggregated = {feature: 0.0 for feature in AGGREGATED_FEATURE_ORDER}
    for name, value in zip(encoded_names, values):
        parent = parent_map.get(name, name)
        aggregated[parent] = aggregated.get(parent, 0.0) + float(value)
    return aggregated
