"""Run LEHAR's alert engine once and print a short summary (LEHAR Phase 4).

The manual, local counterpart of the scheduled job in docs/SCHEDULER.md.
Two modes:

    .venv\\Scripts\\python scripts\\run_alerts_once.py
        In-process: builds the alert engine exactly as the API does and runs
        it against the configured database (backend/.env's DB_PATH or
        DATABASE_URL). No server needs to be running.

    .venv\\Scripts\\python scripts\\run_alerts_once.py --url http://localhost:8000
        Remote: POSTs /api/v1/alerts/run on a running API with the
        X-Alert-Run-Token header — the very call cron-job.org makes, so it
        is also how to test a deployed scheduler setup by hand.

    Add --json for the full run response instead of the summary, and
    --trigger cron to record the run as a scheduled one.

Either way the run is REAL: it fetches live weather/flood data for every
district and raises, suppresses and resolves alerts by the rules in
app/services/alerts/rules.py, and delivers to verified subscribers on any
configured channel. Nothing is simulated (CLAUDE.md rules 4 and 10).
Exit code 0 on a completed run, 1 on a configuration or HTTP error.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.alerts.levels import DISCLAIMER_EN  # noqa: E402

# Generous: a remote run fetches data for all 107 districts before replying.
REMOTE_TIMEOUT_SECONDS = 300.0


def build_engine():
    """The same engine POST /api/v1/alerts/run gets, assembled without
    FastAPI — each provider in app/dependencies.py called directly."""
    from app.dependencies import (
        get_alert_engine,
        get_drift_service,
        get_flood_discharge_client,
        get_flood_forecast_service,
        get_flood_service,
        get_model_service,
        get_weather_service,
    )

    weather = get_weather_service()
    discharge = get_flood_discharge_client()
    model = get_model_service()
    return get_alert_engine(
        flood_service=get_flood_service(discharge, weather),
        weather_service=weather,
        model_service=model,
        drift_service=get_drift_service(model),
        flood_forecast_service=get_flood_forecast_service(discharge, weather),
    )


def run_local(trigger: str) -> dict:
    """One in-process run; returns the same JSON shape the API returns."""
    from app.db import get_session_factory, init_db
    from app.routers.alerts import _run_response

    init_db()  # SQLite: creates tables on a fresh checkout; no-op on Postgres
    engine = build_engine()
    session = get_session_factory()()
    try:
        result = engine.run(session, trigger=trigger)
    finally:
        session.close()
    return _run_response(result).model_dump(mode="json")


def run_remote(base_url: str, token: str, trigger: str, client: httpx.Client | None = None) -> dict:
    """POST {base_url}/api/v1/alerts/run — exactly what the scheduler sends.
    Raises httpx.HTTPStatusError on a non-2xx answer."""
    url = f"{base_url.rstrip('/')}{get_settings().api_v1_prefix}/alerts/run"
    owns_client = client is None
    client = client or httpx.Client(timeout=REMOTE_TIMEOUT_SECONDS)
    try:
        response = client.post(url, params={"trigger": trigger}, headers={"X-Alert-Run-Token": token})
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            client.close()


def format_summary(run: dict) -> str:
    """A few human-readable lines from an AlertRunResponse-shaped dict."""
    duration = run.get("duration_seconds")
    duration_text = f", {duration:.1f} s" if isinstance(duration, (int, float)) else ""
    lines = [
        f"LEHAR alert run #{run.get('run_id')} ({run.get('trigger')}) — started {run.get('started_at')}{duration_text}",
        f"  Districts checked : {run.get('districts_checked', 0)}",
        f"  Alerts raised     : {run.get('alerts_raised', 0)}",
    ]
    suppressed = run.get("suppressed") or []
    reasons = Counter(item.get("reason") for item in suppressed)
    reason_text = ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items()))
    lines.append(f"  Suppressed        : {run.get('alerts_suppressed', 0)}" + (f" ({reason_text})" if reason_text else ""))
    lines.append(f"  Resolved          : {run.get('alerts_resolved', 0)}")
    lines.append(f"  All-clears issued : {len(run.get('all_clear_alert_ids') or [])}")
    raised_ids = run.get("raised_alert_ids") or []
    if raised_ids:
        lines.append(f"  New alert ids     : {', '.join(str(i) for i in raised_ids)}")
    lines.append(run.get("disclaimer") or DISCLAIMER_EN)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="base URL of a running LEHAR API; omit to run in-process")
    parser.add_argument("--token", help="X-Alert-Run-Token for --url (default: ALERT_RUN_TOKEN from backend/.env)")
    parser.add_argument("--trigger", choices=("manual", "cron"), default="manual", help="recorded on the run row")
    parser.add_argument("--json", action="store_true", help="print the full run response as JSON")
    args = parser.parse_args(argv)

    if args.url:
        token = args.token or get_settings().alert_run_token
        if not token:
            print("No run token: pass --token or set ALERT_RUN_TOKEN in backend/.env.", file=sys.stderr)
            return 1
        try:
            run = run_remote(args.url, token, args.trigger)
        except httpx.HTTPStatusError as exc:
            print(f"The API refused the run: HTTP {exc.response.status_code} {exc.response.text}", file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"Could not reach {args.url}: {exc}", file=sys.stderr)
            return 1
    else:
        run = run_local(args.trigger)

    print(json.dumps(run, indent=2, ensure_ascii=False) if args.json else format_summary(run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
