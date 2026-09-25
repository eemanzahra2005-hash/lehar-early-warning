# Monitoring — Prometheus, Grafana, and honest model-performance tracking (Phase 10)

Two independent things live under "Monitoring" in this app:

1. **Infrastructure health** — Prometheus scrapes real metrics off the
   running FastAPI app; a provisioned Grafana dashboard visualizes them.
   Nothing here is synthetic — every number is a real counter/histogram/gauge
   incremented from an actual request.
2. **Model performance (live)** — MAE/RMSE computed ONLY from real
   prediction+actual pairs a user has recorded. Empty (honestly, not with a
   fake chart) until at least one exists — see [Model performance](#model-performance-live) below.

Phase 8's PSI data-drift monitoring (`docs/DRIFT.md`) is unrelated and
unchanged by this phase — both sections share the `#/monitoring` page.

## Starting the stack

The API runs on the **host** (uvicorn), not in Docker:

```
.venv\Scripts\uvicorn app.main:app --reload --app-dir backend
```

Prometheus and Grafana run in Docker Compose:

```
docker compose up -d prometheus grafana
```

| Service    | URL                      | Notes |
|------------|--------------------------|-------|
| API metrics | http://127.0.0.1:8000/metrics | Raw Prometheus exposition format |
| Prometheus | http://127.0.0.1:9090   | Targets page: http://127.0.0.1:9090/targets |
| Grafana    | http://127.0.0.1:3000   | Login `admin` / the `GF_SECURITY_ADMIN_PASSWORD` from your root `.env` |

Stop with `docker compose down` (add `-v` to also delete the named volumes,
which wipes Prometheus's scraped history and Grafana's session state — the
dashboard/datasource themselves are re-provisioned from committed files on
next start regardless, see [Provisioning](#provisioning) below).

## Why `host.docker.internal`

Prometheus runs *inside* Docker Compose, but the API runs on the *host*.
From inside the `prometheus` container, `localhost` means the container
itself — so `monitoring/prometheus.yml` points at `host.docker.internal:8000`
instead. `docker-compose.yml`'s `prometheus` service adds an explicit
`extra_hosts: ["host.docker.internal:host-gateway"]` mapping so this
resolves reliably on Linux Docker Engine too (Docker Desktop on Windows/Mac
already resolves it natively — the mapping is a no-op there, not a
workaround). **The Prometheus target will show `DOWN` if the dev server
isn't running** — that's expected, not a bug; start the API and it flips to
`UP` on the next 15-second scrape.

## Metrics exposed

`GET /metrics` combines two sources:

**Automatic** (prometheus-fastapi-instrumentator, every HTTP request):
`http_requests_total{method,status,handler}`,
`http_request_duration_seconds_bucket{method,handler}` (low-res, per-handler),
`http_request_duration_highr_seconds_bucket` (high-res, no labels — used for
accurate percentiles), request/response size summaries. `status` is grouped
(`2xx`/`4xx`/`5xx`), not the exact code. `/metrics` itself is excluded from
its own instrumentation so the scrape doesn't inflate its own numbers.

**Custom** (`backend/app/metrics.py` — incremented ONLY from real code paths,
per CLAUDE.md rule 4, never on a timer or with demo data):

| Metric | Type | Labels | Incremented when |
|---|---|---|---|
| `predictions_total` | Counter | `source`, `district`, `model_version` | Every `POST /api/v1/predict` that returns a recommendation (`app/routers/predict.py`) |
| `prediction_latency_seconds` | Histogram | — | Wraps the same call: weather resolution + model inference + SHAP explanation + risk score |
| `weather_api_failures_total` | Counter | — | Every failed Open-Meteo weather call — timeout, network error, 4xx/5xx after retries, or an unparseable response (`app/services/weather.py`) |
| `flood_api_failures_total` | Counter | — | Every failed Open-Meteo Flood API (GloFAS) call (`app/services/flood.py`) |
| `assistant_requests_total` | Counter | `provider` | Every successful AI assistant reply, labeled by which provider (`cloud`/`local`) actually answered (`app/routers/assistant.py`) |
| `model_info` | Gauge | `version` | Always `1` for whichever model version is currently served — updated at initial load, promote, and rollback (`app/dependencies.py`'s `set_model_service`) so it changes immediately, no restart needed |

## Provisioning

Nothing is set up by clicking through the Grafana UI — the datasource and
dashboard are both committed files, mounted read-only into the container and
loaded automatically on startup:

- `monitoring/grafana/provisioning/datasources/datasource.yml` — the
  Prometheus datasource (points at the `prometheus` Compose service by name,
  fixed `uid: prometheus` so dashboard panels can reference it directly).
- `monitoring/grafana/provisioning/dashboards/dashboards.yml` — tells Grafana
  to load every `.json` file under `monitoring/grafana/dashboards/`.
- `monitoring/grafana/dashboards/lehar-overview.json` — the "LEHAR Overview"
  dashboard itself (`uid: lehar-overview`). Keep the `uid` stable: it is the
  identity Grafana keys saved panel links, annotations, and alert rules off,
  so renaming it would orphan them.

To change a panel: edit the JSON file directly (or export the edited
dashboard from Grafana's UI back over it) — `allowUiUpdates: false` means a
live in-UI edit doesn't persist across a container restart, by design, so
the committed file stays the single source of truth.

### Dashboard panels

| Panel | What it shows |
|---|---|
| API up/down | Prometheus's own scrape-health signal (`up{job="smart-irrigation-api"}`) — `1` while the last scrape succeeded |
| Current model version | `model_info`'s live label — the exact version currently being served |
| Error rate (4xx/5xx) | Share of responses in the last 5 minutes that were client/server errors, across every route |
| Predictions (last hour) | `sum(increase(predictions_total[1h]))` |
| Request rate | HTTP requests/sec by route (`handler` label) |
| p95 latency | 95th-percentile latency, both overall (`http_request_duration_highr_seconds`) and predict-only (`prediction_latency_seconds`) |
| Predictions per hour by source | `predictions_total` split by `source` (`model_prediction` / `fallback_rule_based` / `rule_flood_override`) — a spike in `fallback_rule_based` means sensor-fault simulations, `rule_flood_override` means the flood cross-link fired |
| Top 10 districts by predictions | `topk(10, sum by (district) (predictions_total))` — cumulative since the API process last started (Prometheus counters reset on restart) |

## Model performance (live)

`GET /api/v1/monitoring/performance` (`backend/app/services/performance.py`)
computes real MAE/RMSE from `actual_observations` joined to
`prediction_logs` — **never a fabricated number, never a demo curve.**

**Why it starts empty**: a prediction's `recommendation_mm` is the model's
*estimate*. Nothing in this app automatically knows what actually got
applied in the field — that has to come from a real human observation. Until
someone records one, there is no ground truth to compare against, so the
endpoint honestly reports:

```json
{"status": "no_actuals_recorded", "count": 0, "rolling_mae": null, "rolling_rmse": null, "series": []}
```

...and the UI shows an instructive empty state rather than an empty chart:
*"Record actual outcomes from the History page to unlock live performance
tracking."*

### Recording an outcome

On the History page (`#/history`), every row without a recorded outcome gets
a **Record actual** button. It opens a small modal (actual mm applied +
optional note), then:

`POST /api/v1/history/{prediction_id}/actual` — auth required; only the
prediction's own owner may record one (404 otherwise, same
non-owner-disclosure pattern as `DELETE /api/v1/fields/{id}`); the value must
be `0–200` mm (`422` outside that range); `409` if this prediction already
has a recorded outcome (`actual_observations.prediction_log_id` is unique —
one recording per prediction, no silent overwrite).

### The math

For every recorded pair: `error = actual_irrigation_mm - recommendation_mm`
(signed, mm — positive means the model *under*-recommended relative to what
was actually applied, negative means it *over*-recommended).

- `rolling_mae` = mean of `|error|` across every recorded pair.
- `rolling_rmse` = sqrt(mean of `error²`) across every recorded pair.
- `series` = every pair's `{date, error}`, chronological, for the
  Monitoring page's error-over-time chart.

"Rolling" here means *continuously updated as new outcomes are recorded* —
not a fixed time-window average like Phase 8's drift `DRIFT_WINDOW`. Every
real recorded pair counts, for as long as the database holds it.

### Where it's used

- `frontend/js/views/history.js` — the Record actual action + modal, and a
  new "Actual" column showing the recorded value once one exists.
- `frontend/js/views/monitoring.js` — the "Model performance (live)" card:
  stats (count, MAE, RMSE) + error-over-time chart when data exists, the
  instructive empty state otherwise. Loaded independently of the Phase 8
  drift section above it — one failing never blocks the other.

## Migration

`actual_observations` (`backend/migrations/versions/c83b98abe752_*.py`) was
autogenerated against the real `db` Postgres service the same way Phase 9's
initial schema was — `alembic revision --autogenerate`, reviewed, then
applied and verified against both a fresh SQLite temp DB
(`backend/tests/test_alembic_migrations.py`) and the real Postgres `db`
service. On SQLite (the zero-setup default), the new table also gets created
automatically by `init_db()`'s existing `create_all()` call — no separate ad
hoc migration step needed there, same as every other table.
