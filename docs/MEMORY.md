# Memory: running the API inside 512 MB

LEHAR's deployed backend targets Render's free web-service tier, which has a
hard **512 MB RAM ceiling** (CLAUDE.md rule 11). An earlier deploy was
OOM-killed on `/api/v1/meta` and `/api/v1/predict` — the process died before
it could answer. This document records what LEHAR Phase 1 changed, and the
**real measured numbers** behind it.

Every number on this page was measured on a running process (CLAUDE.md rule
4 — never fabricated). The commands that produced them are given in full, so
they can be re-run. All predictions are made on SYNTHETIC research data
(CLAUDE.md rule 13).

---

## How the numbers were measured

**Measured against a plain `uvicorn` process, not a container.** Docker
Desktop was not running on the measuring machine (`docker info` → *"failed
to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine"*),
so the containerised `docker run --memory=512m` run could not be performed.
The uvicorn process was measured instead, in the exact environment the
container sets. What this does and does not tell you:

- **Carries over:** Python-level memory — interpreter, imports, the loaded
  model, SHAP, per-request allocations. This is the overwhelming majority of
  the footprint and the part that caused the OOM.
- **Does not carry over:** the measurement was taken on Windows, while the
  deployed container runs Linux/glibc. In particular `MALLOC_ARENA_MAX` is a
  **glibc** setting with no effect on Windows, so its benefit is not
  reflected in these numbers — the Linux figure should be equal or slightly
  better, not worse. The 512 MB limit was also not enforced by the OS here,
  so this measures consumption, not survival under pressure.

**To re-measure inside a container** once Docker Desktop is running:

```
docker build -f backend/Dockerfile -t lehar-backend .
docker run --rm --memory=512m --memory-swap=512m -p 8000:8000 ^
  -e RUN_MIGRATIONS=false -e JWT_SECRET=throwaway-local-value lehar-backend
.venv\Scripts\python scripts\measure_memory.py --base-url http://127.0.0.1:8000
```

(`RUN_MIGRATIONS=false` because the throwaway run has no Postgres to migrate;
the deployed service leaves it `true`.)

**The measurement actually run**, for each of the two profiles below:

```
set MODEL_VERSION=v20260923T212705208535Z
set LOW_MEMORY_MODE=true
set LOG_MEMORY=true
set ENVIRONMENT=production
set MALLOC_ARENA_MAX=2
set WEB_CONCURRENCY=1
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8021 --workers 1

.venv\Scripts\python scripts\measure_memory.py --base-url http://127.0.0.1:8021 --predictions 20
```

`scripts/measure_memory.py` reads RSS from the **server's own**
`GET /api/v1/health/deep` (`rss_mb`), so it reports the serving process's
memory rather than the script's, and works identically against uvicorn, a
container, or a deployed host.

---

## Results

Measured 2026-09-24. Machine: Windows 11, Python 3.14.3. `RSS` = resident set
size of the single uvicorn worker, in MB.

### Deployment profile — compact model, `LOW_MEMORY_MODE=true`

This is what `render.yaml` configures.

| Step | RSS |
|---|---:|
| startup log line (`LOG_MEMORY=true`) | **95.4 MB** |
| after `GET /api/v1/health` | 97.4 MB |
| after `GET /api/v1/meta` | 97.5 MB |
| after 1st `POST /api/v1/predict` | 315.2 MB |
| after 20 `POST /api/v1/predict` calls | **316.0 MB** (steady) |

**Steady-state RSS 316.0 MB — under the 350 MB target, with 196 MB of
headroom against the 512 MB ceiling.**

### Baseline profile — full model, `LOW_MEMORY_MODE=false`

The local-development profile, measured on the same machine for comparison.
This is what local dev still runs, unchanged.

| Step | RSS |
|---|---:|
| startup log line (`LOG_MEMORY=true`) | 318.0 MB |
| after `GET /api/v1/health` | 320.5 MB |
| after `GET /api/v1/meta` | 320.8 MB |
| after 1st `POST /api/v1/predict` | 333.4 MB |
| after 20 `POST /api/v1/predict` calls | 334.2 MB (steady) |

### What changed

| | baseline | deployment | difference |
|---|---:|---:|---:|
| boot (ready to serve) | 318.0 MB | 95.4 MB | **−222.6 MB** |
| steady state | 334.2 MB | 316.0 MB | −18.2 MB |

The decisive difference is **at boot**, and that is the difference that
matters here. Render applies a fixed 5-second-per-check HTTP health check
timeout, and the old profile reached "ready to serve" only after loading a
15.7 MB model and running SHAP's one-time numba JIT warm-up. Starting at
95 MB instead of 318 MB means the process answers `/api/v1/health` promptly
and has room to absorb a request burst before anything approaches 512 MB.

Steady state converges because a `/predict` request legitimately pays for
what it uses: the model is loaded lazily on the first prediction, and the
SHAP explainer is built then too. That cost is real work, not waste — and
both profiles returned the **same recommendation, 14.8 mm**, for the same
sample input.

---

## What produces the reduction

Each of these is a real, independently verifiable change, not a guess:

1. **The compact deployment model** (`MODEL_VERSION` pinned; see below) —
   7.8 MB on disk instead of 15.7 MB, and half the trees to traverse.
2. **`LOW_MEMORY_MODE=true`** — the model is loaded lazily and memory-mapped
   (`mmap_mode="r"`), and the eager SHAP warm-up at boot is skipped. This is
   what moves ~220 MB off the boot path. (LEHAR Phase 1
   measures it and makes it an image default.)
3. **`WEB_CONCURRENCY=1`** — a second uvicorn worker duplicates the entire
   interpreter, the sklearn/numpy/shap import cost and the loaded model. At
   316 MB steady, two workers would not fit in 512 MB. This is the single
   most important setting on this page.
4. **`MALLOC_ARENA_MAX=2`** — glibc otherwise keeps freed memory in up to
   8×CPU per-thread arenas instead of returning it to the OS. No effect on
   the Windows measurement above; applies on the deployed Linux container.
5. **No MLflow in the image** — `backend/requirements-deploy.txt` omits
   `mlflow` (and `pandera`) entirely. `backend/tests/test_no_heavy_imports.py`
   proves at runtime that serving `/health`, `/meta` and `/predict` never
   pulls `mlflow` into `sys.modules`; leaving it uninstalled means it cannot.

---

## The compact deployment model

Trained with the pipeline's own profile flag:

```
.venv\Scripts\python backend\ml\pipeline.py --compact
```

`--compact` sets `n_estimators=60`, `max_depth=10`, and implies
`compare_to_production=False` and `promote_on_pass=False` — it is not trying
to beat the full model on accuracy, and it must not take over local dev's
production pointer. See `COMPACT_N_ESTIMATORS` in `backend/ml/pipeline.py`.

**Real quality-gate output from that run** (thresholds `QG_MAX_MAE=1.0`,
`QG_MIN_R2=0.90`):

```
{
  "metrics": {
    "mae": 0.2513365741006935,
    "rmse": 0.3312862344563467,
    "r2": 0.9958465297326218,
    "n_train": 62744,
    "n_test": 15687,
    "n_estimators": 60,
    "max_depth": 10
  },
  "gate_passed": true,
  "version": "v20260923T212705208535Z"
}

Quality gate reasons:
  - PASS: candidate meets the absolute ceilings QG_MAX_MAE and QG_MIN_R2.
  - Production comparison skipped (compare_to_production=False) — evaluated only
    against the absolute ceilings QG_MAX_MAE/QG_MIN_R2, deliberately not against
    production's MAE (a different deployment profile, e.g. a memory-light model).

Quality gate PASSED. Version v20260923T212705208535Z saved WITHOUT promoting.
```

### Candidates considered

Re-verified with `.venv\Scripts\python scripts\check_deployment_models.py`,
which feeds each registered version's recorded metrics through
`ml/pipeline.py`'s own `quality_gate()` — the same function training uses:

| version | trees | depth | MAE | RMSE | R² | size | gate | SHAP |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `v20260923T212705208535Z` **(deployed)** | 60 | 10 | 0.2513 | 0.3313 | 0.9958 | 7.8 MB | PASS | kept |
| `v20260814T181129195151Z` | 40 | 8 | 0.4570 | 0.6104 | 0.9859 | 1.4 MB | PASS | kept |
| `v20260812T205121116100Z` (local `latest`) | 120 | 10 | 0.2496 | 0.3286 | 0.9959 | 15.7 MB | PASS | skipped |

The earlier 1.4 MB version **does** still pass the gate, and was kept as a
registered option. The 60-tree model was pinned instead because the 6.4 MB it
costs is immaterial against 196 MB of headroom, while its MAE (0.2513) is
within 0.7% of the full model's (0.2496) rather than 83% worse (0.4570).
Accuracy was the scarce resource here, not megabytes.

Both compact candidates sit at or under `LOW_MEMORY_SHAP_MAX_ESTIMATORS`
(default 60), so **per-prediction SHAP explanations keep working** on the
deployed host — confirmed by the measurement above reporting
`explanation: present`. The full 120-tree model exceeds that cap and would
degrade to `explanation: null` under `LOW_MEMORY_MODE`.

### How `MODEL_VERSION` selects it

The compact model is a **normal registered version that deliberately never
became `"latest"`**. `registry.json`'s `"latest"` pointer still names the
full 120-tree model, so local dev, Docker Compose and every test keep serving
that (CLAUDE.md rule 1 — additive, nothing local was replaced).

`ModelService` resolves the version it loads like this
(`backend/app/services/ml_model.py`):

- `MODEL_VERSION=latest` (the default) → follow `registry.json`'s `"latest"`.
- `MODEL_VERSION=<exact version string>` → load exactly that version.

So the compact model is reachable **only** by naming it explicitly:

```
MODEL_VERSION=v20260923T212705208535Z
```

`render.yaml` sets precisely that for the `lehar-api` service, and
`GET /api/v1/health` echoes back whichever version will actually be served,
so a deployed instance can be checked without guessing.

To ship a different compact model later: run `pipeline.py --compact`, commit
the new `backend/ml/model/<version>/` folder plus `registry.json`, update
`MODEL_VERSION` in `render.yaml`, and push. `PRUNE_MODEL_VERSIONS=true` makes
the build drop every other version folder from the image automatically.

---

## Checking memory on a running instance

```
curl https://<your-service>/api/v1/health/deep
```

```json
{
  "status": "ok",
  "environment": "production",
  "model_version": "v20260923T212705208535Z",
  "rss_mb": 316.0,
  "checks": {
    "database": { "status": "ok", "detail": null },
    "model": { "status": "ok", "detail": "v20260923T212705208535Z" }
  }
}
```

`rss_mb` is a real `psutil` reading, or `null` if it could not be taken —
never an estimate. `status` is `"degraded"` (still HTTP 200) if any check
fails, so the body can be read rather than swallowed by an error handler.

**`/api/v1/health/deep` is the diagnostic; `/api/v1/health` is the ping.**
`/health` deliberately touches no database and loads no model, so a slow
database can never fail it and trigger a restart loop. Point uptime monitors
(cron-job.org, Render's own health check) at `/health`, never at `/health/deep`.

With `LOG_MEMORY=true` (set in `render.yaml`) the same reading is written
once to the deploy log at the end of startup:

```
2026-09-24 02:48:15 | INFO | app.memory | Startup memory: RSS 95.4 MB.
```

---

## The flood lead-time model's share (LEHAR Phase 2.5)

Phase 2.5 added a deep-learning flood forecaster. Rule 11 says every
dependency is weighed against the 512 MB ceiling before it is added, so here
is the weighing.

**PyTorch is not installed in the image at all.** It trains the model and
lives in `backend/requirements-ml.txt`; the API loads the *exported* ONNX
graph (~170 KB) with onnxruntime instead. `backend/tests/test_no_heavy_imports.py`
boots the app in a fresh subprocess and asserts `torch` never reaches
`sys.modules` — and torch **is** installed in the local dev venv, which is
what makes that a real assertion rather than a vacuous one.

**onnxruntime is installed, but not imported until it is used.** Measured
with `psutil`, same method as above:

| Step | RSS | Δ |
|---|---:|---:|
| interpreter + numpy (the API already pays this) | 29.5 MB | — |
| `import onnxruntime` | 49.7 MB | +20.2 MB |
| build the `InferenceSession` | 55.9 MB | +6.2 MB |
| after 50 forecasts | 56.2 MB | +0.3 MB |
| **total when the feature is enabled** | | **+26.8 MB** |

`FLOOD_DL_ENABLED` defaults to **false**, and the import sits inside the
method that builds the session (`app/services/flood_forecast.py`), so a
deployment that does not use the feature pays **nothing** — not the 20 MB,
not the session. Against the 196 MB of headroom measured above, 26.8 MB is
affordable when it is switched on.

The session is pinned to one thread each way
(`intra_op_num_threads = inter_op_num_threads = 1`): a 44k-parameter model
over a 14-step sequence is sub-millisecond work, and a thread pool would
cost more RAM than it saves. Full detail: [FLOOD_DL.md](FLOOD_DL.md).

---

## Python version note

`backend/Dockerfile` uses **`python:3.14-slim`**, matching the project's
documented environment and the interpreter the test suite runs on. A move to
`python:3.11-slim` was evaluated during this phase and rejected on evidence:

```
pip download -r backend/requirements-deploy.txt --only-binary=:all: \
  --python-version 3.11 --platform manylinux_2_17_x86_64 ...
```

`numpy==2.5.2` and `shap==0.52.0` publish **no cp311 wheel at all** (numpy
2.5 requires Python ≥3.12), so a 3.11 image cannot install this pinned set.
Downgrading those pins would mean serving `model.joblib` artifacts pickled by
a *different* scikit-learn/numpy than the one that wrote them — precisely the
kind of deploy-only breakage this phase exists to eliminate, and a change to
working code that CLAUDE.md rule 1 asks to be raised rather than made
silently. The same check against 3.14 resolves to **73 prebuilt manylinux
wheels with zero source builds**.
