#!/usr/bin/env python
"""End-to-end smoke test (Phase 13) against a RUNNING Smart Irrigation
instance — pure black-box HTTP calls, no import of app internals, so this
exercises exactly what a real client sees.

Usage:
    .venv\\Scripts\\python scripts\\smoke_e2e.py [--base-url http://localhost:8000]

Also reads SMOKE_BASE_URL from the environment if --base-url isn't given.
Prints a PASS/FAIL table and exits nonzero if anything failed (for CI /
scripted use).

Covers: health -> meta (107 districts) -> register -> field -> predict
(manual weather) -> explanation/risk/confidence present -> history ->
record actual -> performance (count>=1) -> drift -> flood overview ->
models list -> report xlsx + pdf (real magic bytes) -> /metrics has
predictions_total.
"""

import argparse
import os
import sys
import uuid

import requests

TIMEOUT = 30
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SMOKE_BASE_URL", "http://localhost:8000"),
        help="Base URL of the running app (default: http://localhost:8000, or $SMOKE_BASE_URL)",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    api = f"{base_url}/api/v1"

    session = requests.Session()
    token = None
    field_id = None
    predict_json: dict = {}
    prediction_id = None

    # 1. health
    try:
        r = session.get(f"{api}/health", timeout=TIMEOUT)
        ok = r.status_code == 200 and r.json().get("status") == "ok"
        record("health", ok, f"status={r.status_code}")
    except Exception as e:
        record("health", False, str(e))

    # 2. meta -> 107 districts
    try:
        r = session.get(f"{api}/meta", timeout=TIMEOUT)
        districts = r.json().get("districts", []) if r.status_code == 200 else []
        ok = r.status_code == 200 and len(districts) == 107
        record("meta (107 districts)", ok, f"count={len(districts)}")
    except Exception as e:
        record("meta (107 districts)", False, str(e))

    # 3. register
    username = f"smoke_{uuid.uuid4().hex[:12]}"
    try:
        r = session.post(
            f"{api}/auth/register",
            json={"username": username, "password": "SmokeTest123!"},
            timeout=TIMEOUT,
        )
        ok = r.status_code == 201
        if ok:
            token = r.json()["access_token"]
        record("register", ok, f"status={r.status_code} user={username}")
    except Exception as e:
        record("register", False, str(e))

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 4. field
    try:
        r = session.post(
            f"{api}/fields",
            json={"name": "Smoke Test Field", "district": "Lahore", "crop_type": "wheat"},
            headers=headers,
            timeout=TIMEOUT,
        )
        ok = r.status_code == 201
        if ok:
            field_id = r.json()["id"]
        record("field create", ok, f"status={r.status_code} field_id={field_id}")
    except Exception as e:
        record("field create", False, str(e))

    # 5. predict (manual weather - deterministic, no live Open-Meteo dependency)
    try:
        payload = {
            "district": "Lahore",
            "crop_type": "wheat",
            "soil_moisture_pct": 25,
            "canal_flow_cusecs": 450,
            "use_live_weather": False,
            "manual_temperature_c": 32,
            "manual_humidity_pct": 55,
            "manual_rainfall_mm": 2,
            "manual_evapotranspiration_mm": 5,
            "field_id": field_id,
        }
        r = session.post(f"{api}/predict", json=payload, headers=headers, timeout=TIMEOUT)
        ok = r.status_code == 200
        if ok:
            predict_json = r.json()
        record(
            "predict (manual weather)",
            ok,
            f"status={r.status_code} recommendation_mm={predict_json.get('irrigation_recommendation_mm')}",
        )
    except Exception as e:
        record("predict (manual weather)", False, str(e))

    # 6. explanation + risk + confidence present
    has_explanation = predict_json.get("explanation") is not None
    has_risk = predict_json.get("risk") is not None
    has_confidence = predict_json.get("confidence") is not None
    record(
        "explanation+risk+confidence present",
        bool(predict_json) and has_explanation and has_risk and has_confidence,
        f"explanation={has_explanation} risk={has_risk} confidence={has_confidence}",
    )

    # 7. history
    try:
        r = session.get(f"{api}/history", headers=headers, timeout=TIMEOUT)
        rows = r.json() if r.status_code == 200 else []
        ok = r.status_code == 200 and len(rows) >= 1
        if ok:
            prediction_id = rows[0]["id"]  # newest-first; this user has exactly 1 row
        record("history", ok, f"status={r.status_code} rows={len(rows)}")
    except Exception as e:
        record("history", False, str(e))

    # 8. record actual outcome
    try:
        r = session.post(
            f"{api}/history/{prediction_id}/actual",
            json={"actual_irrigation_mm": 8.5},
            headers=headers,
            timeout=TIMEOUT,
        )
        ok = r.status_code == 201
        record("record actual outcome", ok, f"status={r.status_code}")
    except Exception as e:
        record("record actual outcome", False, str(e))

    # 9. performance (count>=1 - exactly 1 on a fresh database, but this
    # endpoint aggregates across ALL users, so >=1 is the robust check on a
    # database that already has prior activity)
    try:
        r = session.get(f"{api}/monitoring/performance", timeout=TIMEOUT)
        count = r.json().get("count", 0) if r.status_code == 200 else -1
        ok = r.status_code == 200 and count >= 1
        record("performance (count>=1)", ok, f"count={count}")
    except Exception as e:
        record("performance (count>=1)", False, str(e))

    # 10. drift
    try:
        r = session.get(f"{api}/monitoring/drift", timeout=TIMEOUT)
        body = r.json() if r.status_code == 200 else {}
        ok = r.status_code == 200 and "status" in body
        record("drift responds", ok, f"status={r.status_code} drift_status={body.get('status')}")
    except Exception as e:
        record("drift responds", False, str(e))

    # 11. flood overview
    try:
        r = session.get(f"{api}/flood/overview", timeout=TIMEOUT)
        n = len(r.json().get("districts", [])) if r.status_code == 200 else 0
        ok = r.status_code == 200 and n > 0
        record("flood overview responds", ok, f"districts={n}")
    except Exception as e:
        record("flood overview responds", False, str(e))

    # 12. models list
    try:
        r = session.get(f"{api}/models", timeout=TIMEOUT)
        ok = r.status_code == 200 and "versions" in (r.json() if r.status_code == 200 else {})
        record("models list", ok, f"status={r.status_code}")
    except Exception as e:
        record("models list", False, str(e))

    # 13. report xlsx (real magic bytes - ZIP "PK")
    try:
        r = session.get(f"{api}/report", params={"format": "xlsx"}, headers=headers, timeout=TIMEOUT)
        ok = r.status_code == 200 and len(r.content) > 0 and r.content[:2] == b"PK"
        record("report xlsx (magic bytes)", ok, f"status={r.status_code} bytes={len(r.content)}")
    except Exception as e:
        record("report xlsx (magic bytes)", False, str(e))

    # 14. report pdf (real magic bytes - "%PDF")
    try:
        r = session.get(f"{api}/report", params={"format": "pdf"}, headers=headers, timeout=TIMEOUT)
        ok = r.status_code == 200 and len(r.content) > 0 and r.content[:4] == b"%PDF"
        record("report pdf (magic bytes)", ok, f"status={r.status_code} bytes={len(r.content)}")
    except Exception as e:
        record("report pdf (magic bytes)", False, str(e))

    # 15. /metrics has predictions_total
    try:
        r = session.get(f"{base_url}/metrics", timeout=TIMEOUT)
        ok = r.status_code == 200 and "predictions_total" in r.text
        record("/metrics has predictions_total", ok, f"status={r.status_code}")
    except Exception as e:
        record("/metrics has predictions_total", False, str(e))

    print()
    name_width = max(len(name) for name, _, _ in results) + 2
    print(f"{'STATUS':<7}{'CHECK':<{name_width}}DETAIL")
    print("-" * (7 + name_width + 40))
    n_fail = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            n_fail += 1
        print(f"{status:<7}{name:<{name_width}}{detail}")
    print("-" * (7 + name_width + 40))
    print(f"{len(results) - n_fail}/{len(results)} passed")

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
