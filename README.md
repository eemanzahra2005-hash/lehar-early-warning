# LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk

<!--
CI badge — reflects real .github/workflows/ci.yml runs on GitHub. It shows
"no status" until the workflow has run at least once on the remote.
-->
[![CI](https://github.com/eemanzahra2005-hash/lehar-early-warning/actions/workflows/ci.yml/badge.svg)](https://github.com/eemanzahra2005-hash/lehar-early-warning/actions/workflows/ci.yml)

LEHAR is a research project by Syeda Eeman Zahra. It is a local, research-grade web application that gives farmers and
agronomy students in Pakistan a daily irrigation recommendation, explains
*why* the model made that call, watches for river-flood risk, and doubles as
a hands-on MLOps teaching platform — real model training, versioning,
quality gates, drift detection, and monitoring, all running entirely on your
own machine. **Every dataset in this project is synthetic research data**
(see [CLAUDE.md](CLAUDE.md) rule 4) — the *weather*, *flood*, and *AI
assistant* data sources are real and live; the historical training data and
district climate parameters are not.

See [CLAUDE.md](CLAUDE.md) for the permanent project rules and
[PROGRESS.md](PROGRESS.md) for LEHAR's phase checklist.

## Features

**Decision Support**
- District/crop irrigation recommendations from a trained RandomForest model
  (live Open-Meteo weather, or manual sensor input, or a rule-based fallback
  when sensors are simulated as faulty)
- Per-prediction SHAP explainability (top factors, signed contributions) and
  a model-agreement confidence interval — never fabricated, `null` when the
  explainer is unavailable
- Optional live soil moisture (Phase 16): Open-Meteo's hourly soil layers,
  depth-weighted to one root-zone value and always labelled as a *model
  estimate, not a field sensor* — off by default, falls back to the manual
  value with a visible note if unavailable (see
  [docs/SOIL_MOISTURE.md](docs/SOIL_MOISTURE.md))
- A transparent, documented Farm (irrigation-stress) Risk Score
- Interactive map, 7-day forecast, multi-district compare, water-savings
  calculator, and full prediction history with CSV export

**Flood Watch**
- A real Flood Risk Index blending GloFAS river-discharge data (Open-Meteo
  Flood API) with recent rainfall and static river exposure, across all 107
  supported districts
- A HIGH flood band automatically overrides an irrigation recommendation to
  0.0mm, with the model's original recommendation preserved and disclosed

**AI Assistant**
- A hybrid chat assistant (cloud-first via Groq's free tier, automatic local
  Ollama fallback) grounded ONLY in real data pulled from the same services
  the rest of the app uses — weather, model, risk, flood, SHAP — never
  invents a number, replies in English/Urdu/Roman Urdu, and shows exactly
  what data it was given

**MLOps**
- A staged training pipeline (validate → split → train → evaluate → quality
  gate → track → register) with MLflow experiment tracking and a local model
  registry
- A quality gate that blocks a worse model from ever reaching production,
  plus one-click promote/rollback with full audit history and hot in-process
  reload (no restart)
- pandera-based data validation and PSI-based drift monitoring against a
  versioned training-time reference distribution

**Monitoring & Reports**
- Prometheus metrics + a provisioned Grafana dashboard for real
  infrastructure/application health
- Honest model-performance tracking (MAE/RMSE) computed only from real
  user-recorded outcomes — empty state until at least one exists, never a
  fabricated curve
- Branded Excel and PDF reports (Phase 12) — model card, field/prediction
  summary, live weather + forecast, filterable prediction history, and
  native charts, generated fresh on every download

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.14, FastAPI, SQLAlchemy |
| ML | scikit-learn (RandomForest), SHAP, MLflow tracking/registry, pandera |
| Database | SQLite (default, zero setup) or PostgreSQL + Alembic (via Docker Compose) |
| Frontend | Vanilla HTML/CSS/JS — no framework, no build step (Chart.js + Leaflet vendored locally) |
| Reports | openpyxl (Excel, incl. native charts), reportlab + matplotlib (PDF) |
| Monitoring | prometheus-fastapi-instrumentator, Prometheus, Grafana (provisioned from committed files) |
| AI Assistant | Ollama (local) and/or any OpenAI-compatible cloud endpoint (Groq by default) |
| Auth | JWT access + refresh tokens, PBKDF2-HMAC-SHA256 password hashing |
| Containerization | Full Docker Compose stack (`api`, `db`, `mlflow`, `prometheus`, `grafana`) — `docker compose up --build` or double-click `START.bat` |

Everything runs **locally** — no cloud services are required. The only
optional exception is the AI assistant's cloud provider (Groq), which is
opt-in and automatically falls back to a fully local model when unset or
unreachable.

## Quick start

### Option A: Docker Compose (recommended — one command, everything included)

Just double-click **`START.bat`** (Windows) / run **`./start.sh`**
(macOS/Linux) — no manual `.env` setup needed (Phase 14): it auto-creates
`.env` and `backend\.env` with a fresh random `JWT_SECRET` on first run
(`scripts\ensure_env.ps1`), checks whether Docker Desktop is installed AND
running, builds + starts everything, waits for the API to become healthy,
then opens **http://localhost:8000** automatically. If Docker isn't
available, `START.bat` automatically falls back to a Python-only mode with
a local SQLite database instead (same as double-clicking
**`STARTUP-NO-DOCKER.bat`** directly) — no manual choice required.
`STOP.bat` stops whichever mode is running; your data is preserved between
runs. See [RUN-ME-FIRST.txt](RUN-ME-FIRST.txt) for the non-technical
walkthrough, or [docs/USER-GUIDE.md](docs/USER-GUIDE.md) for a tour of the
app itself.

Equivalent manual command, if you'd rather not use the script:

```
copy .env.example .env
REM edit .env: set JWT_SECRET, POSTGRES_PASSWORD, GF_SECURITY_ADMIN_PASSWORD

docker compose up --build -d
```

This brings up the API (migrations + model already baked into the image),
PostgreSQL, MLflow, Prometheus, and Grafana — the full stack from the table
below, in one step, no Python install required on the host.

To build a shareable zip of this whole project (for handing to someone
else, or moving to another machine): `scripts\make_release_zip.bat` ->
`lehar-release.zip` at the project root.

`lehar-release.zip` is safe to share publicly — it has no secrets, and asks
the recipient for their own Groq key on first run. For a trusted recipient
only, `scripts\make_full_zip.bat` builds `lehar-release-full.zip`, which is
identical but also includes the real `backend\.env` (with your Groq key).
**`lehar-release-full.zip` contains secrets — share it privately only, never
upload it publicly or commit it.**

### Option B: Python virtual environment (for development)

#### 1. Backend — Python virtual environment

```
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
copy backend\.env.example backend\.env
```

Generate a real `JWT_SECRET` and put it in `backend\.env` (never use the
placeholder default outside throwaway local testing):

```
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(64))"
```

#### 2. Run the dev server

```
.venv\Scripts\uvicorn app.main:app --reload --app-dir backend
```

Open **http://127.0.0.1:8000** — the frontend is served directly by
FastAPI, no separate frontend server needed. A trained model is already
committed under `backend/ml/model/`, so predictions work immediately; SHAP's
one-time JIT warm-up (~30-60s, first run on this machine only) happens
during startup, before the server accepts requests.

#### 3. Optional supporting services (Docker Compose)

```
copy .env.example .env
REM edit the root .env: set POSTGRES_*, GF_SECURITY_ADMIN_PASSWORD

docker compose up -d mlflow
docker compose up -d db
scripts\db_upgrade.bat
docker compose up -d prometheus grafana
```

| Service | URL | Needed for |
|---|---|---|
| App | http://127.0.0.1:8000 | Always (step 2 above) |
| MLflow | http://127.0.0.1:5000 | Training-run tracking/registry UI |
| Grafana | http://127.0.0.1:3000 | Infra dashboards — login `admin` / your `GF_SECURITY_ADMIN_PASSWORD` |
| Prometheus | http://127.0.0.1:9090 | Raw metrics query/targets |

Prometheus and Grafana run in Docker but scrape/monitor the API running on
the **host** (`host.docker.internal:8000`) — the dev server from step 2 must
be running for the Prometheus target to show `UP`. See
[docs/MONITORING.md](docs/MONITORING.md). (Under Option A, Prometheus
scrapes the containerized `api` service instead — see
`monitoring/prometheus.yml`.)

Deploying a hosted demo (Render)? See
[docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) and
[docs/DEPLOY_GITHUB.md](docs/DEPLOY_GITHUB.md) — prepared, not yet pushed
or deployed (see [PROGRESS.md](PROGRESS.md)).

## Training, the quality gate, and promote/rollback

Train a new candidate model through the full staged pipeline (`backend/ml/pipeline.py`:
load → validate → split → train → evaluate → quality gate → track → register):

```
scripts\retrain.bat
scripts\retrain.bat --regenerate    REM also rebuilds the synthetic dataset first
```

The quality gate compares the candidate's real test-split MAE/R2 against the
**current production model's** metrics (`QG_MAE_TOLERANCE`, `QG_MIN_R2`,
`QG_MAX_MAE` — see [docs/MLOPS.md](docs/MLOPS.md)). PASS writes a new
versioned model folder and updates the registry's "latest" pointer; FAIL
touches nothing — the exit code mirrors the verdict. Works fully offline
(falls back to local file tracking under `mlruns/` if the MLflow server at
`docker compose up -d mlflow` isn't running).

Promote or roll back a model version (auth required — easiest from the
**Models** page in the app, or directly via the API):

```
curl -X POST http://127.0.0.1:8000/api/v1/models/v20260812T205121116100Z/promote ^
  -H "Authorization: Bearer <your access token>"

curl -X POST http://127.0.0.1:8000/api/v1/models/rollback ^
  -H "Authorization: Bearer <your access token>"
```

Both hot-reload the served model **in-process** — no server restart — and
are fully audited (`backend/ml/model/registry.json`'s `audit`/`history`
arrays).

## Database modes

- **SQLite (default, zero setup)** — nothing to configure; `init_db()`
  creates `backend/data/app.db` automatically on first run.
- **PostgreSQL (optional, production-style)** — `docker compose up -d db`,
  then `scripts\db_upgrade.bat` to apply Alembic migrations, then set
  `DATABASE_URL` in `backend/.env` to a `postgresql+psycopg://...` URL and
  restart the server. Alembic (not `create_all()`) is the sole source of
  truth for schema once this is set.

Full detail, including why `psycopg` (v3) rather than `psycopg2`, in
[docs/DATABASE.md](docs/DATABASE.md).

## AI Assistant setup (Ollama + optional Groq)

The assistant works with either provider, or both (`LLM_PROVIDER=hybrid`,
the default — cloud first, automatic local fallback):

**Local (Ollama)** — install from [ollama.com](https://ollama.com), then
pull a model matching your available RAM:

```
ollama pull llama3.2:3b      REM <12GB RAM
ollama pull qwen2.5:7b       REM >=12GB RAM — set LLM_MODEL accordingly
```

**Cloud (Groq, optional, free tier)** — get a key at
[console.groq.com](https://console.groq.com), then set
`LLM_CLOUD_API_KEY` in `backend/.env`. Leaving it empty makes `hybrid`
behave exactly like `ollama` (local only, no cloud calls).

`LLM_PROVIDER=none` disables the assistant entirely.

## Testing

```
.venv\Scripts\python -m pytest backend\tests -q
```

**263 tests**, fully offline (weather/soil-moisture/flood providers are faked in
`backend/tests/conftest.py` — no real network calls in the suite). Lint:
`.venv\Scripts\python -m ruff check .` (config in `pyproject.toml`).

## Environment variables

All configuration is via environment variables loaded from `backend/.env`
(never committed — copy from `backend/.env.example`). Every variable below
is read by `backend/app/config.py`'s `Settings`.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk` | Shown in `GET /api/v1/health` |
| `API_V1_PREFIX` | `/api/v1` | API route prefix |
| `ENVIRONMENT` | `local` | `local \| development \| staging \| production` |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000,...` | Comma-separated allowed CORS origins |
| `LOG_LEVEL` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR \| CRITICAL` |
| `DATA_PATH` | `data/synthetic_irrigation_dataset_pk107.csv` | Training dataset CSV (training scripts only, not the API) |
| `JWT_SECRET` | *(placeholder — override!)* | Signs both access and refresh JWTs |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `JWT_REFRESH_EXPIRE_MINUTES` | `10080` (7 days) | Refresh token lifetime |
| `DB_PATH` | `backend/data/app.db` | SQLite file path (used only when `DATABASE_URL` is empty) |
| `DATABASE_URL` | *(empty)* | Full SQLAlchemy URL — set to opt into PostgreSQL |
| `MODEL_VERSION` | `latest` | `"latest"` follows the registry, or pin an exact version |
| `WEATHER_TIMEOUT_SECONDS` | `8.0` | Open-Meteo request timeout (weather and live soil moisture) |
| `WEATHER_CACHE_TTL_SECONDS` | `300` | In-memory weather cache TTL (also per-district live soil moisture) |
| `MAP_OVERVIEW_TTL_SECONDS` | `600` | Cache TTL for the all-districts map overview |
| `FLOOD_CACHE_TTL_SECONDS` | `3600` | Cache TTL for the all-districts flood overview |
| `FLOOD_W_DISCHARGE` | `0.30` | Flood Risk Index component weight |
| `FLOOD_W_RAIN_3DAY` | `0.25` | Flood Risk Index component weight |
| `FLOOD_W_RAIN_INTENSITY` | `0.15` | Flood Risk Index component weight |
| `FLOOD_W_EXPOSURE` | `0.20` | Flood Risk Index component weight |
| `FLOOD_W_MONSOON` | `0.10` | Flood Risk Index component weight |
| `FLOOD_DL_ENABLED` | `false` | Flood lead-time model (`GET /api/v1/flood/forecast/{district}` + FLOOD_FORECAST alerts) — see [docs/FLOOD_DL.md](docs/FLOOD_DL.md) |
| `FLOOD_DL_MODEL_VERSION` | `latest` | Which registered flood lead-time model to serve |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_BOT_USERNAME` / `TELEGRAM_WEBHOOK_SECRET` | *(empty)* | Telegram alert delivery; disabled while empty — see [docs/ALERTS.md](docs/ALERTS.md) |
| `BREVO_API_KEY` / `ALERT_FROM_EMAIL` / `ALERT_FROM_NAME` | *(empty)* / *(empty)* / `LEHAR Alerts` | Email alert delivery via Brevo's HTTPS API; disabled while empty |
| `PUBLIC_BASE_URL` | *(empty)* | Public https:// origin of the API, for email links and the Telegram webhook |
| `ALERT_MAX_SENDS_PER_RUN` | `200` | Cap on Telegram + email sends per alert run (free-tier budget) |
| `RISK_W_MOISTURE_DEFICIT` | `0.35` | Farm Risk Score component weight |
| `RISK_W_ET0_DEMAND` | `0.20` | Farm Risk Score component weight |
| `RISK_W_HEAT_STRESS` | `0.15` | Farm Risk Score component weight |
| `RISK_W_WATER_SCARCITY` | `0.15` | Farm Risk Score component weight |
| `RISK_W_RAIN_RELIEF` | `0.15` | Farm Risk Score component weight (subtracted) |
| `MLFLOW_TRACKING_URI` | `http://127.0.0.1:5000` | MLflow server — falls back to local file tracking if unreachable |
| `QG_MAX_MAE` | `1.0` | Quality gate: absolute MAE ceiling |
| `QG_MAE_TOLERANCE` | `0.05` | Quality gate: how much worse (mm) than production is still acceptable |
| `QG_MIN_R2` | `0.90` | Quality gate: absolute R2 floor |
| `LLM_PROVIDER` | `hybrid` | `hybrid \| ollama \| cloud \| none` |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama server |
| `LLM_MODEL` | `llama3.2:3b` | Local model name (must be pulled first) |
| `LLM_TIMEOUT_SECONDS` | `90.0` | Local chat timeout (CPU inference is slow) |
| `LLM_CLOUD_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `LLM_CLOUD_MODEL` | `openai/gpt-oss-120b` | Cloud model name (Groq's OpenAI-compatible reasoning model) |
| `LLM_CLOUD_API_KEY` | *(empty — cloud disabled)* | Never logged or returned by any endpoint |
| `LLM_CLOUD_TIMEOUT_SECONDS` | `20.0` | Cloud chat timeout |
| `DRIFT_WINDOW` | `200` | Rows compared against the training-time reference distribution |
| `DRIFT_MIN_SAMPLES` | `50` | Below this, drift reports `insufficient_data` |
| `DRIFT_PSI_WARN` | `0.1` | PSI warning threshold |
| `DRIFT_PSI_ALERT` | `0.25` | PSI alert threshold |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `5` | Per-IP limit on `/auth/*` |
| `RATE_LIMIT_PREDICT_PER_MINUTE` | `30` | Per-IP limit on `/predict` |
| `RATE_LIMIT_ASSISTANT_PER_MINUTE` | `10` | Per-IP limit on `/assistant/chat` |
| `LOW_MEMORY_MODE` | `false` | `true` skips the eager SHAP warm-up at boot (built lazily instead) — used on RAM-constrained hosts, see `render.yaml` |

**One file for app settings, in both modes (Phase 15.2):** the Docker
Compose `api` service loads `backend/.env` too (`env_file` in
`docker-compose.yml`), so every variable above — including the assistant's
`LLM_PROVIDER`/`LLM_CLOUD_API_KEY` — is set in `backend/.env` whether you run
with Docker or without. Inside the container, five container-specific values
set by `docker-compose.yml` win instead: `DATABASE_URL` (the `db` service),
`JWT_SECRET` (root `.env`, below), `OLLAMA_BASE_URL` (the host's Ollama),
`MLFLOW_TRACKING_URI` (the `mlflow` service), and `PORT`. After editing
`backend/.env`, restart the stack (`STOP.bat` then `START.bat`, or
`docker compose up -d`).

A separate, **root-level** `.env` (copy from the root `.env.example`) is
read only by `docker compose`, for variable substitution in
`docker-compose.yml` — it is not where app settings go (an
`LLM_CLOUD_API_KEY` left there is ignored; `START.bat` moves one into
`backend/.env` if that file has none):

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` | `irrigation` | `db` service credentials |
| `POSTGRES_PASSWORD` | *(placeholder — override!)* | `db` service credentials |
| `POSTGRES_DB` | `smart_irrigation` | `db` service database name |
| `GF_SECURITY_ADMIN_PASSWORD` | *(placeholder — override!)* | Grafana `admin` login password |
| `JWT_SECRET` | *(placeholder — override!)* | Signs JWTs issued by the containerized `api` service |
| `PORT` | `8000` | Host port the `api` service is published on (`http://localhost:<PORT>`) |

## Troubleshooting

**Port already in use (8000/5000/3000/9090)** — find and stop whatever's
listening, or change the port:
```
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

**"Docker not running" / `docker compose` errors** — start Docker
Desktop first; every Compose service (`mlflow`, `db`, `prometheus`,
`grafana`) is optional — the app runs fully without any of them (SQLite +
no monitoring/tracking).

**Open-Meteo rate limits / 502s from `/weather`, `/forecast`, `/predict`**
— Open-Meteo's free tier has a generous but real rate limit; the app
caches responses (`WEATHER_CACHE_TTL_SECONDS`, default 5 min) and retries
5xx responses automatically, but a sustained burst can still 502. Wait a
minute and retry; this never crashes the app (`WeatherService` always
raises a clean `HTTPException`, never a raw stack trace).

**scikit-learn / model version mismatches** — `backend/requirements.txt`
pins exact versions (CLAUDE.md rule 8); a model trained with a different
scikit-learn version may fail to load or emit a version-mismatch warning.
Retrain with `scripts\retrain.bat` after any dependency upgrade.

**AI assistant shows "Offline"** — Ollama isn't running or the configured
model isn't pulled. Check `GET /api/v1/assistant/status`, which reports
each provider's real availability independently. The rest of the app is
completely unaffected when the assistant is down.

## Synthetic data & limitations

Per [CLAUDE.md](CLAUDE.md) rule 4, **every training dataset and per-district
climate parameter in this project is synthetic** — hand-tuned, plausible
values, not measured meteorological records. This is a student MLOps
research/demo platform, not an agronomic advisory tool; every relevant page
and report carries a "not agronomic advice" disclaimer.

What **is** real, live data:
- Current weather and forecasts (Open-Meteo)
- Live soil moisture when the Predict page's toggle is on (Open-Meteo) —
  real data, but a weather-*model estimate* for a grid cell, not a field
  sensor reading (see [docs/SOIL_MOISTURE.md](docs/SOIL_MOISTURE.md))
- River discharge for Flood Watch (Open-Meteo Flood API / GloFAS)
- Every computed model metric, SHAP value, drift statistic, and monitoring
  number (CLAUDE.md rule 4 — never fabricated, even though the underlying
  training data is synthetic)
- AI assistant replies, grounded only in the above real, live data

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — system diagrams, the `/predict`
  sequence flow, and the MLOps lifecycle
- [docs/API_AUTH.md](docs/API_AUTH.md) — bearer-token auth for API clients:
  the token endpoints, which routes need a token, and the CORS setup a
  separate (non-same-origin) frontend needs
- [docs/MEMORY.md](docs/MEMORY.md) — running the API inside 512 MB: the real
  measured RSS numbers, the compact deployment model and how `MODEL_VERSION`
  selects it
- `docs/SECURITY.md` — auth/rate-limiting/headers hardening, secrets and
  dependency audits
- `docs/DATABASE.md`, `docs/MLOPS.md`, `docs/DATA_VALIDATION.md`,
  `docs/DRIFT.md`, `docs/RISK_SCORE.md`, `docs/FLOOD_RISK.md`,
  `docs/MONITORING.md`
- [docs/ALERTS.md](docs/ALERTS.md) — alert delivery over Telegram and email
  (Brevo): creating the bot, setting the webhook, the Brevo key and sender,
  the double opt-in, delivery rules, and testing locally
- [docs/SOIL_MOISTURE.md](docs/SOIL_MOISTURE.md) — live soil moisture:
  Open-Meteo source, depth weighting, the m³/m³ → `soil_moisture_pct`
  mapping and why, and its honest limits
