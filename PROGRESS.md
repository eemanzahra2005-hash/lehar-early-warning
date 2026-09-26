# PROGRESS.md — LEHAR Phase Checklist

**LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk.**

A research project by Syeda Eeman Zahra. **Baseline platform:**
FastAPI backend, 107 districts, RandomForest model + versioned registry, SHAP
explainability, Flood Watch, the vanilla-JS frontend, the MLOps pipeline
(validate → gate → register), Prometheus/Grafana monitoring, Excel/PDF reports,
Docker Compose, live soil moisture, and 263 passing backend tests.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## Phase 0 — Project setup — **DONE**

- [x] LEHAR name and branding across README, RUN-ME-FIRST.txt, `docs/*.md`,
      frontend, FastAPI title/description, PDF/Excel report headers,
      start/stop scripts, Grafana dashboard, release-zip names, and
      `render.yaml` service names (`lehar-api`, `lehar-db`)
- [x] CLAUDE.md permanent rules, including rule-based alerts, free
      split-stack deployment, the advisory disclaimer, and synthetic-data
      labelling
- [x] ruff clean; full suite green (263 passed)

## Phase 1 — Backend slim for 512 MB + CORS + split-deployment prep — **DONE**

**Measured result: steady-state RSS 316.0 MB, boot 95.4 MB** — under the
350 MB target, with 196 MB of headroom against the 512 MB ceiling. Full
method, commands and comparison table in [docs/MEMORY.md](docs/MEMORY.md).

| | before (full model, `LOW_MEMORY_MODE=false`) | after (compact model, deployment profile) |
|---|---:|---:|
| boot / ready to serve | 318.0 MB | **95.4 MB** |
| after `GET /api/v1/meta` | 320.8 MB | 97.5 MB |
| after 1st `POST /api/v1/predict` | 333.4 MB | 315.2 MB |
| steady (20 predictions) | 334.2 MB | **316.0 MB** |

> Measured against a plain `uvicorn` process, **not** a container: Docker
> Desktop was not running on the measuring machine, so the
> `docker run --memory=512m` variant could not be performed. The uvicorn
> process was run with the exact environment the image sets. `docs/MEMORY.md`
> records this, what carries over (all Python-level memory) and what does not
> (`MALLOC_ARENA_MAX` is glibc-only and has no effect on Windows), plus the
> exact commands to re-measure in a container later.

- [x] Startup memory log (real psutil RSS in MB) behind `LOG_MEMORY=true`,
      taken at the *end* of startup so it reports the true ready-to-serve
      cost in both profiles (`app/services/memory.py`, `app/main.py`)
- [x] `GET /api/v1/health/deep` — database round-trip + model artifact check
      + current RSS; returns 200 with `status: "degraded"` rather than a 500
      when a check fails, so the body stays readable
- [x] `GET /api/v1/health` verified to touch **no** database — it stays the
      cheap uptime ping (Render's health check has a fixed 5 s timeout)
- [x] The API process never imports **mlflow**: `MlflowRegistryService` is now
      a `TYPE_CHECKING`-only import in `app/dependencies.py` and
      `app/routers/models.py`, resolved lazily on the promote/rollback path
      alone. Registry reads on the serving path go through `ml/registry.py`
      (plain `registry.json`) exactly as before. `shap` stays lazily imported
      inside `ExplainService`. Enforced by
      `backend/tests/test_no_heavy_imports.py`, which boots the app in a
      fresh subprocess and asserts on `sys.modules` after real requests —
      results are identical, proven by the unchanged existing tests
- [x] Compact deployment model: `python backend/ml/pipeline.py --compact`
      (`n_estimators=60, max_depth=10`, implying no production comparison and
      no promotion). Trained, passed the **real** quality gate, registered as
      `v20260923T212705208535Z` — **MAE 0.2513, RMSE 0.3313, R² 0.9958**,
      7.8 MB, on the held-out test split (SYNTHETIC research data; gate
      thresholds `QG_MAX_MAE=1.0`, `QG_MIN_R2=0.90`). `registry.json`'s
      `"latest"` is untouched, so local dev still serves the full 120-tree
      model (MAE 0.2496, 15.7 MB) — `MODEL_VERSION` is the only thing that
      selects the compact one, documented in `docs/MEMORY.md`
- [x] The earlier 1.4 MB variant (`v20260814T181129195151Z`, 40 trees) was
      re-run through the gate and **also passes** (MAE 0.4570, R² 0.9859) —
      kept as a registered option, not pinned: 6.4 MB is immaterial against
      196 MB of headroom, while its MAE is 83% worse.
      `scripts/check_deployment_models.py` re-runs the real gate over every
      registered version
- [x] Production defaults set as image defaults in `backend/Dockerfile`:
      `WEB_CONCURRENCY=1`, `LOW_MEMORY_MODE=true`, `MALLOC_ARENA_MAX=2`,
      `RUN_MIGRATIONS=true`, `ENVIRONMENT=production` (so `/health` reports
      `"production"` on Render) — all plain env vars, overridable per
      deployment (CLAUDE.md rule 3)
- [x] CORS for a separate console origin: new `FRONTEND_ORIGINS`
      (comma-separated, default includes `http://localhost:3000`), **merged**
      with the existing `CORS_ORIGINS` rather than replacing it, so this
      repo's own frontend keeps working (CLAUDE.md rule 1). Auth stays
      bearer-token based and is documented for client authors in
      [docs/API_AUTH.md](docs/API_AUTH.md)
- [x] `backend/docker-entrypoint.sh` runs `alembic upgrade head` before
      uvicorn when `RUN_MIGRATIONS=true` (Render free has no shell), with a
      real "off" branch for deployments that migrate out-of-band
- [x] `backend/requirements-deploy.txt` — new serving-only pin set, installed
      by the Dockerfile in place of `requirements.txt`: no dev/test deps, no
      **mlflow**, no **pandera**, no torch (never a dependency here). Pins are
      asserted identical to `requirements.txt` by
      `backend/tests/test_deployment_image.py`, so the image can't drift from
      what the suite ran against. `requirements.txt` is unchanged apart from
      adding `psutil==7.1.3`
- [x] Base image stays **`python:3.14-slim`**. `python:3.11-slim` was
      evaluated and rejected on evidence: `numpy==2.5.2` and `shap==0.52.0`
      publish no cp311 wheel at all (numpy 2.5 requires ≥3.12), so a 3.11
      image cannot install this pinned set, and downgrading those pins would
      mean serving `model.joblib` artifacts pickled by a different
      scikit-learn/numpy than wrote them. Verified with `pip download
      --only-binary=:all:` against both versions; the 3.14 set resolves to 73
      prebuilt manylinux wheels with zero source builds. Recorded in
      `docs/MEMORY.md` and in the Dockerfile header
- [x] Existing vanilla-JS frontend still served locally, unchanged
      (CLAUDE.md rule 7)
- [x] ruff clean; full suite green — **303 passed** (263 existing + 40 new,
      none removed or modified)
- [x] git commit: "phase1: 512MB-safe API + split deployment prep"

**Deferred to Phase 5/6** (needs the console and a live deploy to exist):
end-to-end confirmation that every endpoint the console needs works
cross-origin against the deployed Render instance. The CORS path itself is
covered here by tests that drive a real cross-origin `GET` and an
`OPTIONS` preflight carrying `Authorization` through the actual middleware.

## Phase 2 — Alert engine core — **DONE**

Five farmer-facing levels (1 White Early Advisory, 2 Yellow Advisory, 3 Red
Warning, 4 Purple Urgent Warning, 5 Black Emergency) **inspired by Japan's
five-level disaster alert system**, plus a grey admin-only OPS level 0 that
sits *outside* the farmer ladder (never above level 5). Full farmer-facing
description, every threshold and the reasoning behind each one:
[docs/ALERT_LEVELS.md](docs/ALERT_LEVELS.md); the architecture view is
[ARCHITECTURE.md](ARCHITECTURE.md) section 4.

**An alert row means something is happening.** Level 1 (white) is the calm
baseline and is **computed, not stored**: `GET /api/v1/alerts/active`
returns every district, filling in level 1 for any with no active alert. A
calm 107-district sweep therefore stores **zero** alert rows while still
returning a complete, gapless map — measured, see the smoke sweep below.

- [x] `backend/app/services/alerts/` — one job per module: `levels.py`
      (the single source of truth for colours, EN/UR names, farmer actions
      and channels), `rules.py` (pure threshold functions), `templates.py`
      (deterministic bilingual messages), `channels.py` (the delivery
      interface + the working in-app channel), `ops_events.py`
      (cross-process platform-health breadcrumbs), `engine.py` (the run)
- [x] **Five rule families**, every threshold env-configurable with the
      documented defaults below:
      - `FLOOD` — mapped straight from the existing Flood Risk Index band
        (`app/services/flood.py`), so Flood Watch and the alert engine can
        never disagree about a district: `LOW`→**nothing raised**,
        `WATCH`/`MEDIUM`→2, `HIGH`→3, `HIGH` + discharge rising ≥5% over the
        next 48 h→4, `HIGH` + extreme sub-band (score ≥85) or a ≥20-year
        return period→5. `LOW` is listed explicitly in `FLOOD_CALM_BANDS`
        rather than merely missing from the band map, so its silence is
        visibly a decision. Levels 4/5 are reachable **only from within
        `HIGH`** — a large discharge anomaly alone can still score `LOW`,
        and "evacuate now" must never fire off a calm band
      - `HEAVY_RAIN` — Open-Meteo daily `precipitation_sum`, **wettest
        single day**: ≥30 mm→2, ≥80 mm→3 (deliberately not the 3-day total)
      - `HEAT_STRESS` — Open-Meteo daily `temperature_2m_max`: ≥40 °C on 2+
        **consecutive** days→2, ≥45 °C→3
      - `IRRIGATION_DUE` — saved fields only, always level 1: predicted mm ≥
        the field's own threshold **and** <1 mm rain forecast for 3 days.
        **One alert per saved field per day**, deduped: two fields on the
        same farm are two separate decisions, so the rule carries a
        `field:<id>` subject that scopes its dedupe key, its escalation and
        its resolution — one field going quiet never resolves the other's
      - `OPS` — PSI ≥ `DRIFT_PSI_ALERT`, a quality-gate FAIL, or a rollback
- [x] **Honesty on the 20-year return period** (CLAUDE.md rule 4): GloFAS
      via the free Open-Meteo Flood API publishes **no** return period, so
      the level-5 rarity trigger is a *documented proxy* — forecast peak ≥3×
      the 30-day baseline median. Every alert raised that way records
      `"return_period_is_proxy": true` in its payload and says so in its
      text; a real return period, if one ever becomes available, is used
      directly and clears the flag. Never presented as a computed return
      period
- [x] Dedupe key = `district + type + level + day`, with a **`UNIQUE` index
      on the column** — the database, not just the engine, is what stops two
      concurrent/retried scheduler runs raising the same alert twice. A rule
      scoped narrower than a district widens the type half with its subject
      (`Multan|IRRIGATION_DUE:field:12|1|2026-08-12`), and the engine uses
      `(district, type, subject)` as the identity for escalation, cooldown
      and resolution alike
- [x] Cooldown 12 h (`ALERT_COOLDOWN_HOURS`); **escalation to a higher level
      always creates a new alert and always ignores the cooldown** — a
      farmer must never wait out a cooldown to be told things got worse. The
      superseded lower alert is closed rather than edited, so the record of
      what the farmer was actually told survives (CLAUDE.md rule 1's spirit,
      applied to data)
- [x] Acknowledgement (`POST /api/v1/alerts/{id}/ack`) marks an alert seen
      without resolving it — the condition is still there, so it still
      resolves only when the condition actually goes away
- [x] Resolution after **2 consecutive clear runs** (not 1 — a single failed
      upstream fetch must never declare a flood over), emitting an
      `ALL_CLEAR` alert at level 1: good news never blasts at the urgency of
      the warning it ends
- [x] Four new tables + Alembic migration `b7f3a9c15e42`, SQLite **and**
      PostgreSQL: `alerts`, `alert_subscriptions`, `alert_deliveries`,
      `alert_runs`. Plus one additive nullable column,
      `fields.irrigation_threshold_mm` (NULL = use the env default, which is
      every field saved before this phase)
- [x] Endpoints, all additive: `POST /alerts/run` (guarded by the
      `X-Alert-Run-Token` shared secret; an **unset** `ALERT_RUN_TOKEN`
      means "not configured" and refuses with 503 rather than running
      unauthenticated), `GET /alerts` (district/level/type/status filters +
      pagination), `GET /alerts/active` (**every** district — its highest active level
      with `source: "alert"`, or the computed level-1 calm default with
      `source: "default"`, plus `alerting_count` for the banner),
      `POST /alerts/{id}/ack`, `GET /alerts/levels`, `GET /alerts/stats`
      (JWT)
- [x] Delivery is **in-app + log only** this phase, behind a clean
      `AlertChannel` interface Phase 3's Telegram/email transports drop into
      unchanged. A matching subscription today records an honest
      `status: "skipped"` delivery naming the phase — never a fabricated
      `"sent"` (CLAUDE.md rule 4). An unverified subscription is never
      messaged
- [x] Prometheus: `lehar_alerts_raised_total{type,level}`,
      `lehar_alerts_suppressed_total`, `lehar_alert_run_duration_seconds`
- [x] **Every message ends with "Research advisory — NDMA/PMD/PDMA official
      warnings are authoritative."** in both languages (the Urdu body
      carries the Urdu disclaimer *and* the exact English sentence, so the
      mandated wording is verbatim present whichever language the farmer
      reads) — CLAUDE.md rule 12. Every farmer-facing message also states
      that the model is trained on synthetic data (rule 13). Both are
      asserted by tests over every type/level pair the templates declare
- [x] `WeatherService.fetch_daily_outlook()` added **alongside**
      `fetch_forecast()` rather than changing it (CLAUDE.md rule 1): the
      heat rule needs `temperature_2m_max`, while `fetch_forecast` returns
      `temperature_2m_mean` and every existing caller and test depends on
      that — a district can average 32 °C while peaking at 46 °C
- [x] Smoke sweep over all 107 real districts, offline, measured:

      | sweep | stored alert rows | active map |
      |---|---:|---|
      | calm day (every district `LOW`, 32 °C, no rain) | **0** | 107 districts, 0 alerting, all level 1 |
      | second calm run (nothing accumulates) | **0** | 107 districts, 0 alerting, all level 1 |
      | storm day (rising discharge, 46 °C, 95 mm) | 321 | 107 districts, 107 alerting, all level 5 |

      Both calm runs are still recorded in `alert_runs`, so "the engine ran
      and found nothing" stays distinguishable from "the engine never ran".
- [x] ruff clean; full suite green — **445 passed** (303 existing + 142
      new, none of the existing removed or modified)
- [x] git commits: "phase2: alert engine core", then
      "phase2: level 1 is the computed calm default, not a stored alert"

**Deferred to Phase 3/4** (needs the transports and subscription ownership
to exist): real Telegram/email delivery with per-channel failure isolation,
subscription CRUD endpoints, and revisiting whether `/alerts` and `/ack`
should stay unauthenticated — they are open in this phase for the same
reason `POST /predict` is (a farmer must be able to see and dismiss a flood
warning without an account).

## Phase 2.5 — Flood lead-time model (deep learning, REAL data) — **DONE**

Like a tsunami early warning: predict the **river discharge 1–3 days ahead**
per district, so an alert can fire *before* the flood rather than alongside
it. Flood Watch answers "how bad does the river look
right now"; this answers "where will it be on Thursday". Full methodology,
the real measured numbers and the limitations:
[docs/FLOOD_DL.md](docs/FLOOD_DL.md).

**The irrigation RandomForest is untouched.** This is a second, separate
model for a separate question — and it is the **only** model in LEHAR
trained on REAL data rather than synthetic. CLAUDE.md rules 4 and 13 cut
both ways here: that distinction is stated on the API response, in the model
card and on every alert message, not only in this file.

**Measured result** — registered version `v20260925T164424165573Z`, every
number copied from its `metrics.json` (held-out TEST split, issue day ≥
2024-01-01, 104,834 windows over 106 districts; the full tables are
generated into [docs/FLOOD_DL.md](docs/FLOOD_DL.md)):

| Horizon | Model MAE (log) | Persistence MAE (log) | Model NSE (m³/s) | Persistence NSE (m³/s) | Beats persistence |
|---|---:|---:|---:|---:|:---:|
| D+1 | 0.0341 | 0.0341 | 0.9937 | 0.9953 | **no** (−0.04 %) |
| D+2 | 0.0523 | 0.0569 | 0.9856 | 0.9835 | yes (+8.1 %) |
| D+3 | 0.0645 | 0.0708 | 0.9733 | 0.9679 | yes (+8.9 %) |

Level ≥ 3 early-warning check over 2,433 real event days: **hit rate 0.565
vs 0.458 for persistence** (1,375 vs 1,115 flagged ≥ 24 h ahead), at a
false-alarm ratio of 0.085 vs 0.062. Stated plainly: at **D+1 the model
does not beat persistence**; its value is at D+2/D+3 and in catching more
real flood days earlier, at the cost of somewhat more false alarms.
Dataset: 298,708 real district-days, 2019-01-01 → 2026-09-18, windows
153,488 train / 38,690 val / 104,834 test; 43,555 parameters; early-stopped
at epoch 17 (best 13) after 394.9 s on CPU; ONNX vs PyTorch max abs.
difference 8.34e-07.

*Recovery note (2026-09-25):* the laptop shut down mid-phase with this
section already written but nothing committed, 79/107 districts downloaded
and no model trained. The fetch was resumed (`--start 2019-01-01 --end
2026-09-18 --sleep 2`, 27 more fetched, the 79 skipped as current), the model
was trained and registered, the metrics above were generated from the
artifact, and the unfinished claims in this section were corrected.

- [x] **Environment check first.** A CPU **torch 2.14.0** wheel
      (`torch-2.14.0-cp314-cp314-win_amd64.whl`, resolving to `2.14.0+cpu`)
      installs cleanly into the existing Python 3.14 `.venv` — verified with
      `pip install --dry-run --only-binary=:all:` *before* installing
      anything, and it only ADDS packages (filelock, fsspec, mpmath,
      networkx, sympy). `py --list` shows 3.14 only, so no `.venv-ml` was
      needed and the main venv was never downgraded. `onnxruntime==1.30.0`
      likewise ships a cp314 wheel. `onnxscript` was tested and found **not**
      required (torch's TorchScript exporter needs only `onnx`), so it is not
      pinned. `pip check` clean afterwards
- [x] `scripts/data/fetch_flood_history.py` — REAL daily history for the 107
      districts (106 returned data — GloFAS has **no discharge at Gwadar**'s
      coordinate, recorded as `empty` in the manifest, so the model covers
      106 and the forecast endpoint refuses Gwadar with a 503): GloFAS
      `river_discharge` (Open-Meteo Flood API) + ERA5
      `precipitation_sum`/`temperature_2m_max` (Open-Meteo Archive API),
      joined on UTC days, one `data/flood_history/<district_code>.parquet`
      each. Resumable (a district whose file already reaches the end date is
      skipped), polite (`--sleep` between every call, clear per-district
      progress), and it recognises an **hourly**-limit 429 by its response
      body and waits for the hour to roll over instead of burning retries
      against a closed door. API terms, attribution and the weighted-call
      budget are documented in its module docstring
- [x] **Open-Meteo's free tier is what bounds how much history this model
      gets, and that is recorded rather than glossed over.** The limits count
      *weighted* calls (~`variables × days / 336`), so a 30-year pull for 107
      districts is ~10,400 units against a ~10,000/day, 5,000/hour budget.
      Measured, not theorised: a first attempt at the full history began
      returning 429 at district 24 and exhausted the archive API's hourly
      budget outright — while the flood API still answered 200, so the two
      endpoints have separate budgets. The shipped window is therefore
      **2019-01-01 onwards**, which includes the 2022 catastrophic floods but
      **not** 2010. The script still defaults to `--start 1984-01-01`, so
      anyone with more quota can rerun and retrain with nothing else changed
- [x] `backend/ml/flood_dl/` — split so the SERVING path never needs torch:
      `features.py` (the window/channel contract, numpy only, imported by
      both training and the API), `dataset.py` (windows + per-district
      normalisation, numpy/pandas only), `registry.py` (versioned registry,
      plain JSON), and the three torch-only modules `model.py`, `train.py`,
      `export.py`
- [x] **14-day input window** of `[log discharge, precipitation, tmax,
      day-of-year sin, day-of-year cos]` plus a per-district embedding id →
      log discharge at **D+1, D+2, D+3**. Log space because Pakistan's reaches
      span ~4 orders of magnitude and one big river would otherwise dominate
      the loss; the seasonality *pair* so 31 December and 1 January are
      adjacent rather than 357 days apart. Normalisation is **per district,
      computed on the training rows only** — validation and test days never
      touch it
- [x] **Windows never span a gap.** A window is built only where all 17 days
      are consecutive calendar days with no missing physical value. Stitching
      across a hole would teach the model a jump the river never made; a test
      asserts it over a deliberately holed series, and another asserts a
      window never crosses from one district into the next
- [x] **Split by TIME, never at random**: train ≤ 2022, validation 2023, test
      2024-onwards, keyed on the issue day. A random split on a series this
      autocorrelated scores beautifully and means nothing
- [x] `model.py` — GRU, 2 layers, hidden 64, 16-dim district embedding,
      `Linear(64 → 3)` head. One shared recurrent core learns *how a river
      rises*; the embedding gives each district somewhere to put its own
      character, which 107 separate models could not share
- [x] `train.py` — fixed seeds, Huber loss on normalised log discharge, early
      stopping on validation loss with the **best** weights exported, not the
      last. Writes `metrics.json` with MAE/RMSE/NSE per horizon in **two
      spaces** (log, scale-free; and m³/s, what a hydrologist reads), a
      **PERSISTENCE baseline** ("tomorrow = today") for every one of them, and
      an explicit `beats_persistence` boolean per horizon
- [x] **A level-hit-rate, because MAE is not what an early-warning system is
      for.** Of the test days that really were level ≥ 3 flood days, what
      fraction did the model flag at least 24 h ahead — and how often did it
      cry wolf? Computed through the *same* `forecast_flood_index()` and
      `evaluate_flood_forecast()` the API and the alert engine use, so the
      offline claim and the online behaviour cannot drift apart. Rainfall,
      exposure, month and the 30-day baseline are held identical across model,
      persistence and actual, so only the discharge forecast differs — and
      that simplification (a perfect rain forecast) is recorded inside
      `metrics.json` itself, not only in prose
- [x] `export.py` — ONNX + `norm.json`. The export is **verified before it is
      registered**: the graph is run through onnxruntime at four batch sizes
      and compared against the PyTorch model, refusing to register a mismatch
      above `1e-4`. torch's TorchScript RNN exporter warns unconditionally
      about GRU batch sizes, so the property is proven empirically rather
      than argued about
- [x] `backend/app/services/flood_forecast.py` — inference with
      **onnxruntime only**; no torch import anywhere on the API path. Lazy:
      the onnxruntime import and the session both live inside the first
      forecast actually served, so `FLOOD_DL_ENABLED=false` (the default)
      costs a 512 MB host **nothing**. Measured when enabled: **+26.8 MB RSS**
      (+20.2 import, +6.2 session, +0.3 across 50 forecasts) — see
      [docs/MEMORY.md](docs/MEMORY.md). Session pinned to one thread each way
- [x] **Per-district TTL cache (1 h, the same as Flood Watch's).** Without it
      an alert run would add 107 fresh GloFAS calls per sweep to a free API
      this project had already been rate-limited by — being a courteous
      caller is a requirement here, not a nicety
- [x] **Refuses rather than guesses.** 503 with the reason when the feature is
      off, when no model is registered, when the district was not in the
      training set, when the discharge series is too short, or when a weather
      day the window needs is missing — a fabricated 0 mm would be
      indistinguishable from a real dry day (CLAUDE.md rule 4). A model whose
      `norm.json` disagrees with `features.py` is refused too: it would still
      RUN and still return floats, just meaningless ones
- [x] New alert type **`FLOOD_FORECAST`**, raised on a PREDICTED level ≥ 2,
      payload carrying `lead_time_hours`, `horizon_days`, `model_version`, the
      predicted series, and both the raw and clamped level. Its **own type**,
      not a flag on FLOOD: the two carry different evidence, a farmer must be
      able to tell "the river *is* high" from "the river is *expected* to
      rise", and separate types mean a forecast can never dedupe against,
      supersede or resolve an observed alert. A district can hold both at once
- [x] The level is computed by **delegating to the observed rule's own
      `evaluate_flood()`** with the predicted discharge substituted in — one
      implementation of "what level is this", so a predicted level 3 means
      exactly what an observed level 3 means, one day earlier
- [x] **A forecast never reaches level 4 or 5.**
      `ALERT_FLOOD_FORECAST_MAX_LEVEL` (default 3) stops it one rung below the
      observed rule's ceiling. Levels 4 and 5 take over the farmer's whole
      screen and say *evacuate now*, and a 43,555-parameter research model
      predicting three days out is not evidence enough to say that on its own
      — while the observed FLOOD rule still escalates to 4/5 the moment real
      discharge justifies it. When the clamp bites, the alert records **both**
      levels and says so in its own text. It is configuration, so it can be
      raised later on the evidence in docs/FLOOD_DL.md
- [x] EN/UR messages lead with **"FORECAST, not a measurement"** /
      **"یہ پیش گوئی ہے، پیمائش نہیں"**, name the model version, and state that
      the prediction may be wrong in either direction — a flood it did not
      predict is still possible, and a predicted flood may not arrive. Every
      one still ends with the mandated disclaimer in both languages (rule 12)
      and now also states that *this* model is trained on REAL data while
      LEHAR's irrigation model is not (rule 13). Level 4/5 templates exist
      too, so raising the ceiling could never produce an untranslated alert
- [x] `GET /api/v1/flood/forecast/{district}` — the observed 14-day series,
      the predicted D+1..D+3 series, and the mapped score/band/components/
      level, plus model version, attribution, training-data provenance and the
      disclaimer. `FLOOD_DL_ENABLED` defaults **false**, and `render.yaml`
      states it explicitly rather than relying on the default
- [x] Registered in the existing versioned-registry pattern under
      `backend/ml/flood_dl/model/<version>/` (`model.onnx`, `norm.json`,
      `metrics.json`, plus `registry.json` with a `latest` pointer). A
      separate root from the RandomForest's, because
      `ml/prune_unused_versions.py` treats every directory under
      `backend/ml/model/` as an RF version. A version is never overwritten,
      and an incomplete one never resolves
- [x] torch + onnx pinned in **`backend/requirements-ml.txt` only** — never in
      `requirements.txt`, never in `requirements-deploy.txt`, never in the
      image. `onnxruntime==1.30.0` added to both runtime files.
      `test_deployment_image.py` asserts all of that, and
      `test_no_heavy_imports.py` now boots the app in a fresh subprocess and
      asserts neither `torch` nor `onnxruntime` reaches `sys.modules` — a real
      check, not a vacuous one, since torch IS installed in the dev venv
- [x] Tests run with **no torch, no network and no trained model**: the
      flood-forecast tests load a committed three-district ONNX fixture
      (`backend/tests/fixtures/flood_dl/`, regenerated by
      `scripts/make_flood_dl_test_fixture.py`) whose `metrics.json` labels it
      an untrained fixture, so its meaningless outputs can never be quoted as
      results
- [x] The downloaded history is gitignored (~7 MB of third-party data that is
      re-downloadable at any time), but `data/flood_history/_manifest.json`
      **is** committed, so the provenance of a trained model survives in git
      even though the bytes do not
- [x] `docs/FLOOD_DL.md` written, with its measured-metrics section generated
      from the artifact by `scripts/write_flood_dl_metrics_doc.py` rather than
      transcribed by hand — a number copied from a console into a table is a
      number that can be copied wrong (CLAUDE.md rule 4)
- [x] `docs/ALERT_LEVELS.md`, `docs/FLOOD_RISK.md`, `docs/MEMORY.md`,
      `ARCHITECTURE.md`, `README.md`, `backend/.env.example` and `render.yaml`
      all updated
- [x] `test_flood_dl_registered_model.py` guards the REAL committed artifact
      (the other flood tests only see the fixture): feature contract matches,
      model card says REAL data, `beats_persistence` agrees with its own
      numbers, the split is by time, the graph runs under onnxruntime, and
      docs/FLOOD_DL.md quotes the version that is actually `latest`
- [x] ruff clean; full suite green — **563 passed** (557 before this
      recovery + 6 new, none of the existing removed or modified)
- [x] git commit: "phase2.5: flood lead-time GRU model"

## Phase 3 — Telegram + email (Brevo) delivery channels — **DONE**

Real transports behind Phase 2's unchanged `AlertChannel` interface. Setup,
the bot commands, the delivery rules and local testing:
[docs/ALERTS.md](docs/ALERTS.md).

- [x] `channels.py` became the package `app/services/alerts/channels/`
      (moved with `git mv`; every existing import path still works):
      `base.py` (shared types), `_http.py` (the one retrying HTTPS POST),
      `telegram.py`, `email.py`, and the dispatcher in `__init__.py`
- [x] **Telegram** — Bot API `sendMessage` over HTTPS via httpx (5 s connect
      / 10 s timeouts; 3 retries at 1/2/4 s on network errors, 429 and 5xx,
      honouring a 429's `retry_after` up to 10 s; other 4xx not retried),
      HTML parse mode with escaping, Urdu or English per subscriber, trimmed
      to 4096 chars without losing the disclaimer, and an inline
      **Acknowledge** button. The bot token is redacted from every error
      string and httpx's request logging is quietened so it never reaches a
      log
- [x] Webhook `POST /api/v1/alerts/telegram/webhook`, **webhook mode only**,
      guarded by `X-Telegram-Bot-Api-Secret-Token` (constant-time compare;
      503 while unconfigured, 401 on a wrong/missing secret; always 200
      once authenticated, so Telegram never re-delivers a bad update
      forever). Commands: `/start <district_code>` (deep link
      `t.me/<bot>?start=<code>`; a bare `/start` never subscribes to all
      107 districts), `/stop`, `/level <1-5>`, `/lang en|ur`, `/status`.
      The Acknowledge callback marks the alert acknowledged and records
      *which* chat did, in the alert payload, so reminders stop for that
      chat only. Plus `GET /alerts/telegram/link?district=` for the console
- [x] **Email** via Brevo's transactional API v3 (`/v3/smtp/email`, HTTPS,
      never SMTP). **Double opt-in**: `POST /alerts/email/subscribe` stores
      an unverified row and sends only a confirmation email whose signed
      JWT link expires in 48 h; the requested districts/level/language ride
      inside the signed link and apply only on click, so knowing someone's
      address lets you neither subscribe them nor change their settings.
      `GET /alerts/email/verify`, and `GET`/`POST /alerts/email/unsubscribe`
      (the link in every email, plus RFC 8058 one-click
      `List-Unsubscribe` headers). Bilingual HTML + plain-text emails built
      from the stored template text. Rate-limited like the auth endpoints
- [x] **No schema change.** `/stop` and unsubscribe set `verified=False`
      (unverified is never messaged — the Phase 2 rule), keeping every
      delivery row intact; the migration chain's head is unchanged
- [x] **Delivery pipeline** — one `dispatch_run()` per engine run: fan-out
      to verified subscriptions matching district + `min_level` + channel,
      text in the subscriber's language; **level 1 never leaves the app**;
      **levels 4/5 re-sent every 6 h** while open, to subscribers who have
      not acknowledged, and to anyone who subscribes mid-emergency; decided
      from `alert_deliveries` history alone, so a restart loses nothing
- [x] **Send budget** `ALERT_MAX_SENDS_PER_RUN` (default 200), re-sends
      included, spent **highest level first**; past it, sends are recorded
      as `skipped` / `Deferred: …` and delivered by the next run. A disabled
      channel spends none of it
- [x] **Per-channel failure isolation**: a channel raising or failing never
      blocks the other or the alert; after 3 consecutive failures in a run a
      channel's remaining sends are deferred rather than each burning its
      own retries
- [x] Each `alert_deliveries` row records `status`, `attempts`, `error` and
      `latency_ms` = alert `created_at` → provider 2xx (for a reminder, from
      the run that re-sent it)
- [x] Channels **disable themselves cleanly** when their env is missing —
      an honest `skipped` row naming the missing variable, never `sent`,
      never an error. The existing Phase 2 test asserting that is unchanged
- [x] Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`,
      `TELEGRAM_WEBHOOK_SECRET`, `BREVO_API_KEY`, `ALERT_FROM_EMAIL`,
      `ALERT_FROM_NAME`, `PUBLIC_BASE_URL`, `ALERT_MAX_SENDS_PER_RUN` —
      `config.py`, `backend/.env.example` (commented), `render.yaml`
      (`sync: false` for the secrets), README. `conftest.py` blanks them so
      a real token in a developer's `.env` can never message anyone from
      the suite
- [x] `scripts/set_telegram_webhook.py` — registers the webhook URL + secret
      (`allowed_updates` limited to what is handled, `max_connections=1`
      for the single-worker host) and the command menu; `--info`,
      `--delete`, `--url` for a tunnel; refuses non-HTTPS URLs
- [x] Prometheus: `lehar_deliveries_total{channel,status}`,
      `lehar_delivery_latency_seconds{channel}` histogram
- [x] `httpx==0.28.1` promoted from the dev pins to `requirements.txt` and
      `requirements-deploy.txt` (same version). Weighed against 512 MB:
      **+4.3 MB RSS** measured on top of what the API already imports, and
      loaded only when the channels are first built
- [x] Docs: new [docs/ALERTS.md](docs/ALERTS.md); `docs/ALERT_LEVELS.md`,
      `ARCHITECTURE.md` and the Phase 2 module comments updated
- [x] Tests fully offline — every Telegram/Brevo call goes through a real
      `httpx.Client` over `httpx.MockTransport`: send + retry/backoff +
      token redaction, webhook auth + every command + the Acknowledge
      callback, email send + the whole opt-in flow, fan-out matching, the
      budget cap and deferred retry, 6 h re-sends and per-chat ack, failure
      isolation, latency, metrics, and the webhook script
- [x] ruff clean; full suite green — **643 passed** (563 existing + 80 new,
      none of the existing removed or modified)
- [x] git commit: "phase3: telegram + email delivery channels"

**Not verified against the live providers** — no bot token or Brevo key
exists on the development machine, so every provider interaction was
tested against mocked HTTP only. The first real send is a Phase 6
(deployment) check.

## Phase 4 — Subscriptions, admin stats, scheduler docs — **DONE**

A small operations phase. The existing code was audited first and **only
the missing pieces were added**. Nothing was removed and no existing test
was changed. **No schema change and no new migration:**
`test_alerts_migration.py` pins the Alembic head to the Phase 2 revision,
and every Phase 4 figure could be derived from the tables that already
exist.

- [x] **Audit — already present from Phases 2/3:** email subscribe (rate-limited,
      schema-validated), signed verify/unsubscribe links (incl. RFC 8058
      one-click POST), Telegram `/start`/`/stop` + `GET /alerts/telegram/link`,
      `GET /alerts/stats` (totals by status/type/level, deliveries by status,
      last run). `/api/v1/health` was already DB-free.
- [x] **Subscription API completeness** (`routers/alert_channels.py`):
      - verify, unsubscribe and the Telegram link are now rate-limited with
        the existing slowapi limiter, on the new
        `RATE_LIMIT_SUBSCRIPTION_PER_MINUTE` (20). Subscribe keeps the
        tighter auth limit.
      - bilingual JSON: `message_en`/`message_ur` + `disclaimer_ur` on
        subscribe (Phase 3's `detail` kept).
      - `?format=json` on verify/unsubscribe returns
        `SubscriptionResultResponse` (`verified` / `unsubscribed` /
        `invalid_link`) with the same status code. HTML stays the default,
        byte-for-byte as before.
      - `TelegramLinkResponse` schema, now with `bot_username`,
        `start_command` and bilingual instructions.
- [x] **`GET /alerts/stats` additions** (`services/alerts/summary.py`, all
      additive fields):
      - raised and resolved per type × level
      - `suppressed_total` (durable, from `alert_runs`)
      - deliveries per channel × status
      - median/p95 delivery latency per external channel, over at most the
        latest 5000 sends, so memory stays bounded
      - `active_subscriptions` (verified) and a per-channel split
      - `last_run.duration_seconds`
- [x] **Suppressed per type × level is scoped honestly.** `alert_runs` stores
      only a per-run count, so the breakdown comes from a new
      `lehar_alerts_suppressed_detail_total{type,level,reason}` counter. The
      response labels it `suppressed_breakdown_scope: "since_process_start"`.
      Making it durable would need a schema change, which was left for a
      later phase. The original unlabelled `lehar_alerts_suppressed_total`
      is unchanged.
- [x] **`GET /alerts/health-summary`** (public, no auth):
      - national highest active level + districts per level 1–5, built on
        the same `highest_active_by_district` rows as `/alerts/active`
      - cached `ALERT_HEALTH_SUMMARY_TTL_SECONDS` (60 s) with
        `Cache-Control`; a run or an ack invalidates the cache immediately
      - both disclaimers included
- [x] **`scripts/run_alerts_once.py`** — one real run, with either an
      in-process engine or `--url` (the exact POST + `X-Alert-Run-Token` the
      scheduler sends). Prints a short summary or `--json`, with the
      disclaimer.
- [x] **[docs/SCHEDULER.md](docs/SCHEDULER.md)** covers:
      - the cron-job.org job (POST `/alerts/run?trigger=cron` every 30 min
        with `X-Alert-Run-Token`) and request-timeout behaviour
      - optional UptimeRobot on `GET /api/v1/health` every 5 min
      - why `/health` must not touch the DB (Neon compute hours; restart
        loops)
      - the Render free 750 h/month budget with and without a pinger
      - a GitHub Actions cron alternative, documented but deliberately not
        committed as a workflow
- [x] `render.yaml` gained `ALERT_RUN_TOKEN` (`sync: false`). Without it the
      deployed `/alerts/run` refuses every scheduled call.
- [x] **Grafana:** an *Alerts* row on the provisioned LEHAR Overview
      dashboard, titled with the disclaimer. Panels: raised by level,
      deliveries by channel/status, delivery latency p95, and last alert
      run, which uses new `lehar_alert_last_run_timestamp_seconds` +
      `lehar_alert_last_run_outcomes{outcome}` gauges. The existing panels
      are untouched.
- [x] Env: `RATE_LIMIT_SUBSCRIPTION_PER_MINUTE`,
      `ALERT_HEALTH_SUMMARY_TTL_SECONDS` in `config.py` + `backend/.env.example`
      + README
- [x] Docs: [docs/ALERTS.md](docs/ALERTS.md) §5 API reference,
      [docs/MONITORING.md](docs/MONITORING.md) metrics + panels, README links
- [x] Tests (offline), in three new files:
      - `test_alerts_operations.py`: stats breakdowns, latency percentiles,
        health-summary caching/invalidation/agreement with `/active`,
        gauges, and dashboard integrity (unique ids, no overlap, every
        queried metric really exported). Also asserts `/health` runs **zero
        SQL statements** and `render.yaml` declares the token.
      - `test_alert_subscriptions_api.py`: the full JSON opt-in flow,
        validation, the Telegram link, and 429s on every public subscription
        endpoint.
      - `test_run_alerts_once_script.py`: the real engine in-process, and
        the remote request against `httpx.MockTransport`.
- [x] ruff clean; full suite green — **700 passed** (643 existing +
      57 new, none of the existing removed or modified)
- [x] git commit: "phase4: subscriptions, stats, scheduler docs"

**Not verified against live services:** cron-job.org, UptimeRobot, Render
and Neon were not configured from the development machine. The schedule is
documented and the exact request is tested against a mock and in-process.
The first real scheduled run is a Phase 6 check.

## Phase 5 — Next.js Early-Warning Console (in this repo, `console/`)

> The console lives in this repository under `console/` and Vercel deploys it
> with Root Directory = `console`. It was first planned as a separate
> repository; Phase 5a moved it in-repo. CLAUDE.md rule 7 covers only
> `frontend/`.

- [~] New Next.js console in `console/` talking to this API. Scaffold +
      pages done in 5a
- [x] Flood views carry the research-advisory disclaimer (CLAUDE.md rule 12).
      Every console page shows it in the footer in EN + UR
- [x] This repo's vanilla-JS frontend stays as-is (`frontend/` untouched in 5a)

## Phase 5a — Next.js Early-Warning Console: scaffold + pages — **DONE**

A new Next.js 16 (App Router, TypeScript, Tailwind 4, ESLint) app in
`console/`. **No backend code changed.** Details:
[console/README.md](console/README.md).

- [x] Scaffold (npm, `src/`), with every dependency pinned exactly. Runtime
      deps are kept small: `react-leaflet` + `leaflet`, `recharts`,
      `lucide-react`. `pakistan_districts.geojson` is copied to
      `console/public/geo/`. The root `.gitignore` ignores
      `console/node_modules`, `console/.next` and `console/.env*.local`
- [x] Level design system:
      - CSS tokens (L1 white, L2 yellow, L3 red, L4 purple, L5 black, OPS
        grey) mirror `levels.py`. A test reads `levels.py` to prove they
        match and that every pair meets WCAG AA
      - never colour alone: always icon + level number + name
      - names and actions come live from `GET /alerts/levels`
- [x] Typed API client (`src/lib/api.ts`) mirroring `schemas.py`:
      - base URL from `NEXT_PUBLIC_API_URL`
      - bearer token in `localStorage` for admin calls, with one refresh on 401
      - "server waking up" handling: network error or bare 502/503/504 is
        retried with backoff for up to 60 s behind an EN/UR banner. LEHAR's
        own JSON 503s are not retried; they are shown as the honest reason
- [x] Pages: `/` Alert Board (aria-live national banner, district cards
      sorted by level, 48 h all-clear notices, **Level 4/5 full-screen
      takeover** with colour flash, big number, actions, Acknowledge, sound
      toggle OFF by default), `/map` (choropleth + district panel: 7-day
      observed discharge + DL D+1..D+3 forecast, falling back to Flood Watch
      observations on 503), `/alerts` + `/alerts/[id]`, `/subscribe`
      (Telegram deep link, email double opt-in), `/predict` (+ top SHAP
      reasons), `/explain`, `/admin` (login, stats, models, drift). EN/UR
      toggle with RTL. Disclaimer in EN + UR on every page
- [x] Takeover "Acknowledge" is **per device** (`localStorage`), because
      `POST /alerts/{id}/ack` clears an alert for every visitor. The global
      ack is shown only to a logged-in admin on the detail page
- [x] Quality gates: `npm run lint`, `npx tsc --noEmit` and `npm run build`
      pass. vitest: **25 passed** (level mapping + token drift + contrast,
      i18n completeness + placeholder parity, API retry/backoff, flood
      series)
- [x] CI: new `console` job in `.github/workflows/ci.yml` (npm ci, lint,
      typecheck, test, build on Node 24)
- [x] Measured first-load JS (production build, from
      `.next/diagnostics/route-bundle-stats.json`, gzip computed locally):
      ~146–151 KB gzip on every route except `/explain` (262 KB gzip,
      recharts). The map's chart is lazy-loaded, so `/map` stays at 151 KB
- [x] Smoke test against a locally running backend: every route answers
      200 with the disclaimer in the HTML; response shapes match the types;
      CORS allows `http://localhost:3000`
- [x] Backend gaps listed in `console/README.md`: no `GET /alerts/{id}`,
      unauthenticated global ack, no server-side OPS exclusion or time filter
      on `GET /alerts`, and no list of forecast-capable districts

**Not verified in a real browser.** No browser automation was available on
the development machine. The pages were checked by build, typecheck, lint,
unit tests and HTTP smoke tests only. Leaflet rendering, the takeover
(which needs a real level-4/5 alert) and the RTL layout still need a manual
look (with screenshots into `docs/screenshots/`) before Phase 6.

## Phase 6 — Free deployment (Neon + Render + Vercel + cron-job.org)

- [ ] PostgreSQL on Neon (free tier)
- [ ] FastAPI backend on Render free (512 MB)
- [ ] Console on Vercel
- [ ] Scheduled alert evaluation via cron-job.org
- [ ] No paid services anywhere in the stack (CLAUDE.md rule 11)

## Phase 7 — Evaluation toolkit for the paper

- [ ] Reproducible evaluation scripts
- [ ] Real computed numbers only — never fabricated metrics (CLAUDE.md rule 4)
- [ ] Synthetic training data stays labelled as synthetic (CLAUDE.md rule 13)

## Phase 8 — Paper

- [ ] Write-up backed by the Phase 7 evaluation outputs
