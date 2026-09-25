"""Pure-python feature/label schema constants — CROPS and the model's
feature-column layout.

Deliberately kept free of pandas/numpy/scikit-learn imports (unlike
train_model.py and generate_data.py, which need those to actually train/
generate data). app/services/ml_model.py, app/services/explain.py, and
app/validators.py all need these plain lists at serving time but must never
be forced to import pandas/sklearn just to read them (LOW_MEMORY_MODE, Phase
13.1 — see docs/DEPLOY_RENDER.md) — so this module exists as the single
lightweight source of truth, imported directly by the serving path.
train_model.py/generate_data.py re-export these same names so every existing
`from ml.train_model import FEATURE_COLUMNS` / `from ml.generate_data import
CROPS` call site (training scripts, tests) keeps working unchanged.
"""

CROPS = ["wheat", "cotton", "rice", "sugarcane", "maize"]

CATEGORICAL_FEATURES = ["district", "crop_type"]
NUMERIC_FEATURES = [
    "temperature_c",
    "humidity_pct",
    "rainfall_mm",
    "evapotranspiration_mm",
    "canal_flow_cusecs",
    "soil_moisture_pct",
    "was_imputed",
    "month",
    "day_of_year",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET_COLUMN = "irrigation_recommendation_mm"
