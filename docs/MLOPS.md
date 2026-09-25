# MLOps — training pipeline, quality gate, promote/rollback (Phase 7)

> This is a **local, single-machine MLOps demo**, not a production ML
> platform. The quality-gate thresholds below are pragmatic project
> defaults chosen to be reasonable for this synthetic dataset — they are
> **not scientific constants**, and nothing here is a substitute for real
> domain-expert model validation.

## Overview

Two things drove the current model into production before Phase 7:
`backend/ml/train_model.py` (train once, save, done) and a hand-maintained
`backend/ml/model/registry.json` (the `"latest"` pointer
`app/services/ml_model.py` reads at startup). Both **still exist and still
work exactly as before** — Phase 7 does not touch or break either.

What Phase 7 adds on top is `backend/ml/pipeline.py`, a staged pipeline with
explicit, logged stages:

```
load_data -> validate -> split -> train -> evaluate -> quality_gate -> track -> register
```

Every run is logged to MLflow (params, metrics, artifacts, tags) for audit —
**pass or fail**. Only a PASSing candidate gets written to
`backend/ml/model/<version>/` and promoted via `registry.json`'s `"latest"`
pointer — the exact same dual files/format the existing API already reads,
so nothing downstream had to change (`ModelService`, `ExplainService`, the
Predict/Explainability/Map pages, etc. are all unaware Phase 7 happened).

## The quality gate

`backend/ml/pipeline.py`'s `quality_gate()` compares the candidate's real,
computed-on-the-held-out-test-split metrics against the **current
production model's** metrics (read straight from `registry.json`), using
three env-configurable thresholds (`backend/app/config.py`,
`backend/.env.example`):

| Env var             | Default | Meaning |
|----------------------|---------|---------|
| `QG_MAX_MAE`         | `1.0`   | **Absolute ceiling.** The candidate's MAE (mm) must never exceed this, regardless of how the current production model is doing. |
| `QG_MAE_TOLERANCE`   | `0.05`  | How much worse (mm) than the *current production model's* MAE a candidate is still allowed to be. A candidate that's better never needs this. |
| `QG_MIN_R2`          | `0.90`  | **Absolute floor.** The candidate's R2 on the test split must be at least this. |

### Decision matrix

| Situation | Verdict |
|---|---|
| No production model exists yet | PASS if the candidate meets `QG_MAX_MAE` and `QG_MIN_R2` alone (nothing to compare against). |
| Candidate MAE ≤ production MAE | PASS ("better or equal"). |
| production MAE < candidate MAE ≤ production MAE + `QG_MAE_TOLERANCE` | PASS ("slightly worse, within tolerance"). |
| Candidate MAE > production MAE + `QG_MAE_TOLERANCE` | **FAIL** ("worse"), even if it's still under `QG_MAX_MAE`. |
| Candidate R2 < `QG_MIN_R2` | **FAIL**, regardless of MAE. |
| Candidate MAE > `QG_MAX_MAE` | **FAIL** ("ceiling breach"), regardless of production. |

The gate is intentionally **asymmetric**: it only ever blocks a worse
candidate from becoming production. It never blocks or auto-rolls-back an
already-serving model — a known-good production model is never touched by a
failed training run (`registry.json` is left completely untouched on FAIL).

### On PASS

1. `model.joblib`, `metrics.json`, `feature_importance.json`,
   `global_shap.json`, `reference_stats.json` are written to a new
   `backend/ml/model/<version>/` directory (never overwrites an existing
   version — CLAUDE.md rule 6).
2. `registry.json`'s `"latest"` pointer is updated to the new version, with
   extra Phase 7 metadata on that version's entry: `"source": "pipeline"`,
   `seed`, `dataset_hash`, `mlflow_run_id`, `mlflow_model_version`, and the
   gate's own reasons — so the Models page can show exactly why it passed.
3. The model is registered in the MLflow Model Registry as `irrigation-rf`
   with the alias `champion` (best-effort — see "MLflow tracking" below).

### On FAIL

1. `registry.json` is **not touched**. The current production model keeps
   serving.
2. No versioned model directory is written.
3. The MLflow run is still fully logged (params/metrics/artifacts/tag
   `quality_gate=fail`) — rejected candidates stay auditable, they just
   never go live.
4. The pipeline (and `scripts/retrain.bat|sh`) exit with a **nonzero** code,
   so a scheduled/CI run can detect the rejection without parsing output.

## MLflow tracking

`docker-compose.yml` runs the official MLflow server locally:

```
docker compose up -d mlflow
```

- UI: <http://127.0.0.1:5000>
- Backend store: SQLite at a named Docker volume (`mlflow_data`), so runs
  and the model registry survive container restarts.
- Configured via `MLFLOW_TRACKING_URI` (`backend/.env.example`, default
  `http://127.0.0.1:5000`).

**Training must work fully offline.** Before every run, the pipeline pings
`{MLFLOW_TRACKING_URI}/health` with a 2-second timeout. If that fails (the
container isn't running), it logs a clear warning and falls back to local
file tracking under a `mlruns/` directory at the project root (gitignored) —
no training run is ever blocked on the MLflow server being up. The tradeoff:
the bare local file store doesn't reliably support the MLflow Model
Registry in every MLflow version, so registry/alias calls are wrapped in
their own try/except and simply skipped (with a warning) if they fail — the
local `registry.json` dual-write is what actually keeps the app working
either way.

## How to train a new candidate

```
scripts\retrain.bat
```

or directly:

```
.venv\Scripts\python backend\ml\pipeline.py
```

Options: `--n-estimators N` (default 120), `--max-depth N` (default 10),
`--seed N` (default 42). Add `--regenerate` to `scripts\retrain.bat`/`.sh`
to rebuild the synthetic dataset first (`backend/ml/generate_data.py`) —
off by default, since the dataset rarely needs to change between runs.

The script prints the quality-gate reasons and exits `0` on PASS, `1` on
FAIL. Check the printed MLflow run URL (or <http://127.0.0.1:5000>) for the
full metrics/artifacts/residuals plot.

## How to promote / roll back

The pipeline auto-promotes a PASSing candidate. To manually promote a
*different* already-trained version (e.g. roll forward to an older one, or
promote a version trained on another machine), use the API
(`backend/app/routers/models.py` — auth required, reuses the existing
login):

```
POST /api/v1/models/{version}/promote
POST /api/v1/models/rollback
```

Both are also available from the **Models page** (`#/models`) in the app,
with a confirmation modal. Promotion:

1. Validates the target version's artifacts exist on disk and its metrics
   pass the **absolute ceilings** (`QG_MAX_MAE`, `QG_MIN_R2`) — not the
   tolerance-vs-production check, since this is an explicit human decision,
   not an automated candidate evaluation.
2. Pushes the current production version onto `registry.json`'s `"history"`
   list, sets `"latest"` to the target version, and appends an audit entry
   (`{action, version, username, timestamp}`).
3. Hot-reloads the in-process `ModelService` (and, cascading from it, the
   SHAP `ExplainService` and every service built on top of them) — the
   Explainability page and every prediction reflect the new version
   immediately, no server restart needed.
4. Best-effort updates the `champion` alias on the corresponding MLflow
   model version, if that version has one recorded (pipeline-trained
   versions do; pre-Phase-7 "legacy" versions don't, and are promotable all
   the same).

**Rollback** promotes whatever is at the top of `"history"` — i.e. the
previous production version — through the exact same code path above. If
`"history"` is empty (nothing to roll back to), it returns `400`.

## Scheduling (off by default)

Because the quality gate blocks a worse model from ever reaching
production, it's safe to put `scripts\retrain.bat` on a recurring schedule
(Windows Task Scheduler) or cron (`scripts/retrain.sh`) if you want
periodic retraining without babysitting it — a FAILing run just leaves the
current production model in place and exits nonzero. This project does
**not** set up such a schedule by default; it's documented here only as a
safe option if you choose to add one yourself.
