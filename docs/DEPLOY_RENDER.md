# Deploying to Render

Phase 13 prepared everything needed to deploy LEHAR to
[Render](https://render.com) as a free-tier hosted demo; the service is now
live. **Nothing in this repository deploys automatically** — Render redeploys
on every push to the connected branch, per its own dashboard settings, not
because of anything in this repo. Render requires the repository to be on
GitHub first — see [DEPLOY_GITHUB.md](DEPLOY_GITHUB.md) for that step.

**Phase 13.1 — 512MB-safe deployment profile.** The free-tier web service
has a hard 512MB RAM ceiling; the first deploy under Phase 13's plain
`LOW_MEMORY_MODE=true` setting alone still got OOM-killed on every request
past `/health` (see PROGRESS.md Phase 13.1 for the full memory diagnosis).
This section documents what changed and why — see also the `render.yaml`
comments.

## What gets deployed

- `render.yaml` (repo root) — a Render **Blueprint**: one Docker web
  service (`lehar-api`, built from `backend/Dockerfile`, same image as the
  local `docker compose` "api" service) plus one free PostgreSQL database
  (`lehar-db`).
- The web service's entrypoint (`backend/docker-entrypoint.sh`) runs
  `alembic upgrade head` against the Render Postgres database, then starts
  uvicorn bound to Render's `$PORT` — identical to the local Docker path,
  no Render-specific code.
- `LOW_MEMORY_MODE=true`, `ENVIRONMENT=production`, `WEB_CONCURRENCY=1`,
  `MALLOC_ARENA_MAX=2`, `RUN_MIGRATIONS=true`, `LOG_MEMORY=true`,
  `FRONTEND_ORIGINS=<console origin>`, `MODEL_VERSION=<compact version>`, and
  `PRUNE_MODEL_VERSIONS=true` are all set for this service — see the
  `render.yaml` comments next to each. **[docs/MEMORY.md](MEMORY.md) has the
  real measured RSS numbers** behind every one of them (LEHAR Phase 1). In short:
  - `LOW_MEMORY_MODE=true` — the model is loaded lazily (not at boot), via
    a memory-mapped (`mmap_mode="r"`) `joblib.load()`; the SHAP explainer is
    skipped entirely for any model over `LOW_MEMORY_SHAP_MAX_ESTIMATORS`
    (default 60) estimators, degrading to `explanation: null` exactly like
    any other explainer failure (Phase 6's never-fabricate contract —
    `confidence` is unaffected, since it doesn't depend on SHAP).
  - `MODEL_VERSION` is pinned to the **compact deployment model**
    (`v20260923T212705208535Z` — 60 trees, max depth 10, 7.8MB vs the full
    model's 15.7MB), trained with `python backend/ml/pipeline.py --compact`
    specifically for this RAM ceiling and gate-verified at MAE 0.2513 /
    R² 0.9958 on synthetic research data. It sits at the SHAP cap above, so
    per-prediction explanations still work on Render. The local dev /
    Docker-Compose production pointer (`registry.json`'s `"latest"`) is
    untouched and still serves the full model. See
    [MEMORY.md](MEMORY.md) for how `MODEL_VERSION` selects it and for the
    other compact candidates that were considered.
  - `WEB_CONCURRENCY=1` and `MALLOC_ARENA_MAX=2` keep a single worker and
    stop glibc hoarding freed memory in per-thread arenas.
  - `RUN_MIGRATIONS=true` makes `backend/docker-entrypoint.sh` apply
    `alembic upgrade head` before starting uvicorn — Render free has no
    shell, so this is the only way migrations get applied there.
  - `LOG_MEMORY=true` writes one real psutil RSS reading to the deploy log
    at the end of startup (`Startup memory: RSS 95.4 MB.`), and
    `GET /api/v1/health/deep` reports current RSS at any time.
  - `FRONTEND_ORIGINS` allows the separate Vercel-hosted console to call
    this API cross-origin. Auth is bearer-token based, so there are no
    cookie/`SameSite` concerns — see [API_AUTH.md](API_AUTH.md).
  - The image installs `backend/requirements-deploy.txt`, a serving-only
    subset that omits **mlflow** and **pandera** entirely. The API process
    can therefore never import the heaviest dependency in the project;
    `backend/tests/test_no_heavy_imports.py` enforces the same thing at
    runtime.
  - `/api/v1/meta` and the district list no longer import pandas/numpy/
    scikit-learn at all (previously pulled in transitively just to read a
    5-item crop list) — see `backend/ml/feature_schema.py`.
  - The Docker image itself is pruned to just the served model version (see
    `PRUNE_MODEL_VERSIONS` above and `backend/ml/prune_unused_versions.py`)
    — this shrinks the image, not runtime RAM (unloaded files on disk don't
    consume process memory), but every MB of build/deploy time helps on a
    free-tier build.

## What does NOT get deployed

- MLflow, Prometheus, and Grafana — these are local-only monitoring/MLOps
  tooling (CLAUDE.md: "everything runs locally"). The hosted demo serves
  predictions from the model version already committed under
  `backend/ml/model/`; retraining/promoting still happens on your own
  machine via `scripts\retrain.bat` and the Models page.
- A local Ollama server — there's nothing to fall back to on a hosted
  machine, so `LLM_PROVIDER=cloud` is set explicitly (not the local-first
  `hybrid` default). Without an `LLM_CLOUD_API_KEY` set, the assistant is
  simply unavailable (`GET /api/v1/assistant/status` reports
  `available: false`) — the rest of the app is unaffected, same honest
  degradation as every other optional feature in this app.

## Step-by-step

1. **Push the repo to GitHub first.** Render's Blueprint deploy reads
   `render.yaml` from a connected GitHub repository — see
   [DEPLOY_GITHUB.md](DEPLOY_GITHUB.md) for the exact commands.

2. **Create a Render account** at <https://render.com> (free tier is
   enough for this Blueprint) and connect your GitHub account under
   Account Settings -> Connected Accounts.

3. **New -> Blueprint.** Pick the `lehar-early-warning` repo. Render
   detects `render.yaml` at the repo root automatically and shows a
   preview: one web service (`lehar-api`) and one database (`lehar-db`),
   both on the free plan. Click **Apply**.

4. **First deploy will fail health checks until you set the secrets.**
   That's expected — `render.yaml` deliberately leaves `JWT_SECRET` and
   `LLM_CLOUD_API_KEY` as `sync: false` (never auto-generated or committed).
   Go to the `lehar-api` service -> Environment, and set:
   - `JWT_SECRET` — generate a real random value:
     ```
     python -c "import secrets; print(secrets.token_urlsafe(64))"
     ```
   - `LLM_CLOUD_API_KEY` — optional, a free key from
     <https://console.groq.com/keys>. Leave empty to run without the AI
     assistant (everything else works fine).

   `DATABASE_URL` is already wired automatically (`render.yaml`'s
   `fromDatabase` reference to `lehar-db`) — Render injects its own
   Postgres connection string, and `app/db.py`'s
   `_normalize_postgres_scheme()` rewrites the bare `postgres://` prefix
   Render uses to the `postgresql+psycopg://` scheme this app's driver
   needs, automatically. Nothing to edit there.

5. **Save, and Render redeploys automatically.** Watch the deploy log —
   you should see `Applying database migrations (alembic upgrade head)...`,
   then `Startup memory: RSS <n> MB.` (from `LOG_MEMORY=true`), then
   `Uvicorn running on http://0.0.0.0:$PORT`. That RSS line is the number to
   watch against the 512MB ceiling; compare it with the measurements in
   [MEMORY.md](MEMORY.md). The health check path is `/api/v1/health`; once
   it passes, the service goes live at the
   `https://lehar-api-xxxx.onrender.com` URL Render assigns.

6. **Verify.** Open the assigned URL — the full frontend loads (same
   static files as local). Try `/api/v1/health`, `/api/v1/meta`, and a
   manual-weather prediction from the Predict page. `/api/v1/health/deep`
   additionally reports the database, the model and current RSS:

   ```
   curl https://lehar-api-xxxx.onrender.com/api/v1/health/deep
   ```

   Or measure RSS across the whole request sequence:

   ```
   .venv\Scripts\python scripts\measure_memory.py --base-url https://lehar-api-xxxx.onrender.com
   ```

   Run `scripts/smoke_e2e.py` against the live URL for a full check:
   ```
   .venv\Scripts\python scripts\smoke_e2e.py --base-url https://lehar-api-xxxx.onrender.com
   ```

## Health-check timing (not configurable — verified, not assumed)

Render's own docs (Health Checks, render.com/docs/health-checks) specify a
fixed 5-second-per-check timeout for HTTP health checks — `render.yaml` has
no field to raise this (only `healthCheckPath`, already set to
`/api/v1/health`, and `maxShutdownDelaySeconds`, which governs graceful
*shutdown*, not startup). So the real mitigation isn't a config knob, it's
what Phase 13.1 already does: `/api/v1/health` never touches the model (no
pandas/sklearn import, no DB query beyond the process being alive) and the
lazy-loading changes above keep boot-time memory low enough that the
process reliably reaches "Uvicorn running" well inside Render's check
window, instead of getting OOM-killed before ever answering a health check.

## Known free-tier limitations (be aware, not blockers)

- Render's free web services **spin down after 15 minutes of inactivity**
  and take ~30-60s to wake back up on the next request — the first request
  after idle will be slow, not broken.
- Render's free Postgres plan **expires after 90 days** unless upgraded.
- No persistent disk on the free web service — this is fine, since the
  app's only persistent state is the database (Postgres, not SQLite) and
  the model artifacts (baked into the image at build time, not written to
  at runtime).

## Updating the deployed model

The Docker image bakes in whatever is currently committed under
`backend/ml/model/`. To ship a newly promoted model version, commit the
new version's folder (`git add backend/ml/model/<new-version>/
backend/ml/model/registry.json`) and push — Render redeploys automatically
on every push to the connected branch (or trigger a manual deploy from the
Render dashboard).

**Render's `MODEL_VERSION` is pinned to a specific compact version string,
not `"latest"`** — promoting a new version locally (Models page /
`scripts\retrain.bat`) changes `registry.json`'s `"latest"` pointer but does
**not** change what Render serves. To ship a new compact model to Render:

```
.venv\Scripts\python backend\ml\pipeline.py --compact
```

`--compact` trains at `n_estimators=60, max_depth=10`, gates against the
absolute ceilings only, and registers the result **without** moving
`"latest"` — then prints the version string to set. (Pass explicit
`--n-estimators`/`--max-depth`/`--sample-frac` to override the profile; keep
`n_estimators` at or under `LOW_MEMORY_SHAP_MAX_ESTIMATORS`, default 60, if
you want SHAP explanations to keep working there.)

Then commit the new version folder + `registry.json`, update `MODEL_VERSION`
in `render.yaml` (the `PRUNE_MODEL_VERSIONS`-driven build arg picks it up
automatically — see `backend/ml/prune_unused_versions.py`), and push.

To compare candidates before pinning one, `scripts\check_deployment_models.py`
re-runs the real quality gate over every registered version and prints each
one's metrics, size and verdict.
