# Scheduling LEHAR's alert runs (Phase 4)

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> LEHAR is a research project; its alerts are never official warnings.

LEHAR's alert engine does nothing on its own. An alert run (evaluate all
107 districts → raise / suppress / resolve → deliver) happens only when
something calls:

```
POST {PUBLIC_BASE_URL}/api/v1/alerts/run?trigger=cron
X-Alert-Run-Token: <ALERT_RUN_TOKEN>
```

This page covers how to trigger that call on a schedule, for free, and why
it is set up the way it is.

**Why there is no scheduler inside the API.** On Render's free plan the web
service **spins down after 15 minutes without inbound traffic**
([DEPLOY_RENDER.md](DEPLOY_RENDER.md)). An in-process scheduler (APScheduler,
a background thread) stops when the process does, so it would silently miss
every run while the service sleeps. It would also double-run if the
service were ever scaled to two instances. An **external** scheduler fixes
both: its HTTP request is what wakes the service, and there is exactly one
caller.

---

## 1. Set the run token

1. Generate a long random secret, for example:

   ```
   .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Set it as `ALERT_RUN_TOKEN`:
   - locally in `backend/.env`;
   - on Render under **lehar-api → Environment**. `render.yaml` declares it
     with `sync: false`, so the value is never committed.

While `ALERT_RUN_TOKEN` is empty, `/alerts/run` refuses every call with
**503**. A wrong or missing header gets **401**. The comparison is
constant-time (`hmac.compare_digest`).

---

## 2. cron-job.org (the recommended scheduler)

[cron-job.org](https://cron-job.org) is free and needs no server. Create
**one** job:

| Field | Value |
|---|---|
| URL | `https://<your-api>.onrender.com/api/v1/alerts/run?trigger=cron` |
| Schedule | every **30 minutes** (`*/30 * * * *`) |
| Request method | **POST** |
| Headers | `X-Alert-Run-Token: <your ALERT_RUN_TOKEN>` |
| Body | none |
| Notifications | on failure (so you hear about a 401/503) |

`?trigger=cron` records the run as scheduled rather than manual in
`alert_runs.trigger`. That keeps scheduled and hand-triggered runs apart in
`GET /api/v1/alerts/stats`.

**Why every 30 minutes.** The upstream data changes slowly: Open-Meteo's
flood discharge is daily, and its weather forecast updates hourly at best.
Running more often would add no new information, but it would spend free
compute and wake the database more often. Alert behaviour is **not tied to
the interval.** Dedupe is per UTC day, cooldown is `ALERT_COOLDOWN_HOURS`,
and resolution takes `ALERT_CLEAR_RUNS_TO_RESOLVE` consecutive clear runs
([ALERT_LEVELS.md](ALERT_LEVELS.md)). Running hourly instead only means an
all-clear takes about 2 h rather than about 1 h.

**Request timeouts.** A cold start (roughly 30–60 s on Render free) plus a
full sweep can take longer than cron-job.org's maximum request timeout on
the free plan. If the job times out, cron-job.org reports a failure, **but
the run still completes on the server**, because `/alerts/run` is a
synchronous handler and keeps running after the client disconnects. To
check what actually happened, read `last_run` in `GET /api/v1/alerts/stats`
or the Grafana *Last alert run* panel, not only the job's status.

**Concurrency.** Two overlapping runs cannot duplicate an alert.
`alerts.dedupe_key` is `UNIQUE` in the database itself, so the second run's
duplicate is suppressed ([ALERT_LEVELS.md → Dedupe](ALERT_LEVELS.md)).

---

## 3. Optional: UptimeRobot on `/api/v1/health`

[UptimeRobot](https://uptimerobot.com)'s free plan can send
`GET https://<your-api>.onrender.com/api/v1/health` every **5 minutes**.
This has two effects:

1. **Monitoring.** You get an email when the API is actually down.
2. **Keep-warm.** A request every 5 minutes is less than Render's 15-minute
   idle window, so the service never spins down. Every cron run and every
   farmer's page load then skips the cold start.

### Why `/health` must never touch the database

`GET /api/v1/health` reads a few KB of `registry.json` and nothing else. It
opens no database connection (see [`routers/health.py`](../backend/app/routers/health.py)
and `test_health_deep.py` / `test_alerts_operations.py`, which count the SQL statements it runs: zero). This is deliberate, for two reasons.

- **Neon compute hours.** Neon's free plan suspends the Postgres compute
  when it has been idle for about 5 minutes and bills compute time only
  while it is awake, against a fixed monthly allowance. If a ping every
  5 minutes ran even `SELECT 1`, the compute would never reach its idle
  window. It would stay awake around the clock (30 days × 24 h ≈ **720
  compute-hours a month**) and use up the free allowance for no benefit.
  With a DB-free `/health`, the database wakes only for real work: alert
  runs, logins, predictions and console views.
- **No restart loops.** Render also uses `/health` as the service's health
  check (`healthCheckPath` in `render.yaml`). If `/health` depended on the
  database, a slow or suspended Neon compute would fail the check. Render
  would then restart a healthy API process, over and over.

`GET /api/v1/health/deep` **does** query the database. Use it by hand for
diagnostics and **never** point a pinger at it. The same applies to
`GET /api/v1/alerts/health-summary`. It is cached for 60 s, but it is still
a database read, and it exists for the console banner, not for uptime
checks.

### The Render free 750 h/month budget

Render gives each workspace **750 free instance-hours per month**, shared
across all its free web services. A 31-day month is 744 h.

| Setup | lehar-api awake | Fits in 750 h? |
|---|---|---|
| cron-job.org every 30 min, **no** pinger | about 15 min of every 30 (it spins down 15 min after each run) → **~370 h/month**, plus console traffic | yes, with room for another free service |
| cron-job.org **+** UptimeRobot every 5 min | 24/7 → **~720–744 h/month** | yes, but only just, and **no other free web service** in the workspace can then stay up all month |

So UptimeRobot is **optional**. Leave it off if you want the free hours for
another service, or if cold starts are acceptable for a research demo. Turn
it on if fast first responses and down-alerts matter more. Either way, the
30-minute alert schedule is the same.

**Keep in mind when the service sleeps:** in-process state resets on every
spin-down. That includes the Prometheus counters,
`/alerts/stats`' `suppressed_by_type_and_level` (which is why it is labelled
`since_process_start`), the rate-limit windows and the health-summary
cache. Everything in the database persists: alerts, deliveries, runs,
subscriptions, and every other `/stats` figure.

---

## 4. Alternative: GitHub Actions cron

If you would rather keep the schedule next to the code, a workflow can make
the same call. Add two repository secrets, `LEHAR_API_URL` (for example
`https://lehar-api.onrender.com`, no trailing slash) and `ALERT_RUN_TOKEN`,
then create `.github/workflows/alerts-cron.yml`:

```yaml
name: alert-run
on:
  schedule:
    - cron: "*/30 * * * *"   # UTC
  workflow_dispatch: {}       # "Run workflow" button for a manual run

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: POST /api/v1/alerts/run
        env:
          LEHAR_API_URL: ${{ secrets.LEHAR_API_URL }}
          ALERT_RUN_TOKEN: ${{ secrets.ALERT_RUN_TOKEN }}
        run: |
          curl --fail-with-body --silent --show-error \
               --max-time 300 --retry 2 --retry-delay 30 \
               -X POST "$LEHAR_API_URL/api/v1/alerts/run?trigger=cron" \
               -H "X-Alert-Run-Token: $ALERT_RUN_TOKEN"
```

Caveats compared with cron-job.org:

- GitHub runs scheduled workflows **on a best-effort basis**. Under load a
  run can start many minutes late, or occasionally be skipped.
- GitHub **disables scheduled workflows in a public repository after 60
  days without repository activity**. Re-enable it from the Actions tab.
- Minutes are free for public repositories. Private repositories draw on
  the account's free monthly minutes, and each run here uses about one.

This snippet is documentation only. It is not committed as a workflow, so
nothing starts calling a deployment until you add it on purpose.

---

## 5. Running once by hand

`scripts/run_alerts_once.py` performs one real run and prints a short
summary:

```
.venv\Scripts\python scripts\run_alerts_once.py
```

```
LEHAR alert run #42 (manual) — started 2026-09-26T06:00:00Z, 38.4 s
  Districts checked : 107
  Alerts raised     : 3
  Suppressed        : 5 (cooldown 1, duplicate 4)
  Resolved          : 1
  All-clears issued : 1
  New alert ids     : 311, 312, 313
Research advisory — NDMA/PMD/PDMA official warnings are authoritative.
```

(The numbers above only show the format. Your run prints whatever the rules
actually decided from live data.)

- With no arguments it runs **in-process** against the database configured
  in `backend/.env`, and no server needs to be running.
- `--url http://localhost:8000` (or your deployed URL) sends **the exact
  request the scheduler sends**, using `ALERT_RUN_TOKEN` from `backend/.env`
  or `--token`. This is the quickest way to test a cron-job.org setup
  before saving it.
- `--trigger cron` records the run as scheduled. `--json` prints the full
  run response.

A run is always real. It fetches live weather and flood data, applies the
rules, and **delivers to verified subscribers** on every configured channel.
To run without messaging anyone, leave the Telegram and Brevo variables
unset: each channel then disables itself cleanly ([ALERTS.md](ALERTS.md)).

On Windows, Task Scheduler can run the same command every 30 minutes if
you want periodic runs on a local-only install. No cloud service is needed
(CLAUDE.md rule 5).

---

## 6. Checking that the schedule works

- **`GET /api/v1/alerts/stats`** (JWT) → `last_run` shows the trigger,
  start/finish, `duration_seconds` and outcome counts. `total_runs` should
  grow by about 48 a day on a 30-minute schedule.
- **Grafana → LEHAR Overview → Alerts row → *Last alert run*** shows how
  long ago the last run finished. It turns orange past 35 minutes and red
  past an hour ([MONITORING.md](MONITORING.md)).
- **`GET /api/v1/alerts/health-summary`** is what the public console banner
  shows: the national highest active level and districts per level.
