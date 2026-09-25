# Data validation (Phase 8)

Two independent layers check for impossible/corrupted values, at two very
different points in the system's lifecycle:

1. **Training data validation** (`backend/ml/validation.py`) — runs on the
   whole training CSV before every `backend/ml/pipeline.py` run. Uses
   [pandera](https://pandera.readthedocs.io/) to check every row against a
   schema in one pass, never trains on data that fails it.
2. **Prediction input validation** (`backend/app/schemas.py`) — runs on
   every `POST /api/v1/predict` / `POST /api/v1/compare` request via
   Pydantic `Field(ge=, le=)` constraints. Rejects a single impossible
   value (e.g. `temperature_c=80`) with a `422` before it ever reaches the
   model, the Farm Risk Score, or `prediction_logs`.

Both layers use the **same physical bounds** (table below) so a value that
would fail training-data validation can never sneak in through the
prediction API either.

## The bounds

| Field                     | Range         | Reasoning |
|----------------------------|---------------|-----------|
| `temperature_c`            | `-10 to 55`   | Coldest recorded Pakistan winter lows to the hottest recorded summer highs (Jacobabad/Turbat-class extremes), with margin. |
| `humidity_pct`              | `0 to 100`    | Physical definition of relative humidity. |
| `rainfall_mm`               | `0 to 400`    | Generous ceiling above Pakistan's heaviest recorded single-day monsoon totals — catches corrupted/garbage values, not realistic heavy-rain days. |
| `evapotranspiration_mm`     | `0 to 20`     | Reference ET0 rarely exceeds ~12-14mm/day even in extreme heat+wind; 20 leaves headroom without accepting nonsense. |
| `canal_flow_cusecs`         | `0 to 2000`   | Above the largest of this project's synthetic per-district canal-command baselines (`backend/ml/districts.py`), with margin. |
| `soil_moisture_pct`         | `0 to 100`    | Physical definition (volumetric/relative sensor reading, 0-100%). |
| `irrigation_recommendation_mm` (target) | `0 to 100` | The synthetic target formula never produces values outside this range; a value outside it in real training data indicates corruption, not just an unusual crop/day. |

These are **generator-informed heuristics, not agronomic constants** — see
`docs/RISK_SCORE.md` and `docs/FLOOD_RISK.md` for the project's stance on
this kind of pragmatic threshold. They're deliberately wide enough that the
real generated dataset (`data/synthetic_irrigation_dataset_pk107.csv`)
passes with comfortable margin on every column (verified against the
actual min/max of every numeric column before picking these bounds) — the
goal is to catch corrupted/garbage/mis-typed data, not to second-guess
realistic-but-unusual weather.

`soil_moisture_pct` is the one column marked **nullable** in the pandera
schema: `backend/ml/generate_data.py` deliberately injects sensor faults
(`missing_sensor`, `stuck_sensor`) into a small fraction of rows before
imputing them (forward-fill from the previous day, flagged via
`was_imputed`). The schema describes the physical sensor reading honestly
— a raw, pre-imputation reading really can be missing — even though the
actual generated CSV has zero nulls anywhere today (imputation always runs
before the file is written). Every other required column is non-nullable.

## Layer 1: training data validation

`backend/ml/validation.py`'s `validate_training_data(df)`:

- Builds a `pandera.pandas.DataFrameSchema` from the bounds table above,
  plus `crop_type` restricted to the 5 known crops
  (`backend/ml/generate_data.py`'s `CROPS`) and `district` restricted to
  the 107 known districts (`backend/ml/districts.py`'s `DISTRICTS`).
- Validates with `lazy=True` — every violation in the dataset is collected
  in one pass, not just the first row that fails.
- Separately computes a **missing-values report** (null count per required
  column) and an **unexpected-category report** (exact unknown
  district/crop values found, not just pass/fail) — useful even when the
  schema check below would already fail the run, since a human reading the
  report wants the actual bad values.
- Returns a `ValidationReport` (`passed`, `n_rows`, `n_columns`, `errors`,
  `missing_values`, `unexpected_categories`) — never raises on its own.

`backend/ml/pipeline.py`'s `validate()` stage calls this and raises
`DataValidationError` (a `ValueError` subclass carrying the report) if
`passed` is `False`. `run_pipeline()` **never proceeds past this stage** on
failure — no split, no training, no registry write. The report is logged
to MLflow as a `validation_report.json` artifact either way:

- **Pass**: attached to the same MLflow run as the rest of that training
  run's artifacts (`feature_importance.json`, `reference_distribution.json`,
  etc. — see `track_run()`).
- **Fail**: training never runs, so `log_validation_failure_run()` opens a
  standalone, lightweight MLflow run (dataset path/hash/row-count params,
  a `validation: fail` tag, the `validation_report.json` artifact) purely
  so the failed attempt is still auditable — mirroring Phase 7's "every run
  logs to MLflow regardless of outcome" contract, extended to cover a
  failure that happens before training even starts.

Run it directly on the real dataset:

```
.venv\Scripts\python -c "import sys; sys.path.insert(0,'backend'); import pandas as pd; from ml.validation import validate_training_data; from ml.train_model import resolve_data_path, load_dataset; r = validate_training_data(load_dataset(resolve_data_path())); print(r.to_dict())"
```

or just run `scripts\retrain.bat` — validation is always the first stage.

## Layer 2: prediction input validation

`backend/app/schemas.py`'s `PredictRequest` (and the pre-existing
`CompareRequest`/`FieldCreate`) use `Field(ge=, le=)` on every numeric
field, with the identical bounds from the table above:

```python
manual_temperature_c: float | None = Field(default=None, ge=-10, le=55, ...)
```

FastAPI/Pydantic reject an out-of-range value with an HTTP `422` before the
request handler ever runs — the model never sees it, nothing is written to
`prediction_logs`, and `middleware.py`'s uniform error handler wraps it in
the app's standard `{"error": "validation_error", "detail": [...], ...}`
shape. Each `detail` entry names the exact field (`loc`) and the violated
bound (`msg`, e.g. *"Input should be less than or equal to 55"*) — a clear,
readable rejection, never a silently-accepted or silently-clamped value.

`soil_moisture_pct` (`0-100`) and `canal_flow_cusecs` (`0-2000`) already had
these bounds since Phase 3; Phase 8 added them to the four manual-weather
override fields (`manual_temperature_c`, `manual_humidity_pct`,
`manual_rainfall_mm`, `manual_evapotranspiration_mm`), which previously
accepted any float.

## Never fabricated, per CLAUDE.md rule 4

Both layers report REAL, computed results — an empty `errors` list really
means the schema check passed on every row, and `missing_values`/
`unexpected_categories` are the actual counts/values found, never a
placeholder. There is no "assume valid" fallback: a dataset that can't be
validated is treated as failing, not skipped.
