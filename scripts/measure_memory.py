"""Measure the API process's real RSS across a request sequence (LEHAR Phase 1).

The deployed backend has a hard 512MB ceiling (Render free tier, CLAUDE.md
rule 11) and was previously OOM-killed on /api/v1/meta and /api/v1/predict.
This script produces the numbers docs/MEMORY.md records: RSS at boot, then
after each endpoint that mattered in that incident.

It measures whatever process is serving `--base-url`, by asking the API
itself via GET /api/v1/health/deep (`rss_mb`) — so it reports the SERVER's
memory, not this script's, and works identically against a local uvicorn, a
container, or a deployed host.

Usage (start the server separately, in the profile you want to measure):

    .venv\\Scripts\\python -m uvicorn app.main:app --app-dir backend --port 8000
    .venv\\Scripts\\python scripts\\measure_memory.py

    # or against a container / a deployed instance
    .venv\\Scripts\\python scripts\\measure_memory.py --base-url http://127.0.0.1:8000

Every number printed is a real reading taken from the running process
(CLAUDE.md rule 4). If the server cannot measure its own RSS, this prints
"unavailable" rather than a substitute number. All predictions use SYNTHETIC
research data (CLAUDE.md rule 13).
"""

import argparse
import json
import sys

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 120

SAMPLE_PREDICTION = {
    "district": "Lahore",
    "crop_type": "wheat",
    "soil_moisture_pct": 25.0,
    "canal_flow_cusecs": 300.0,
    "use_live_weather": False,
    "manual_temperature_c": 30.0,
    "manual_humidity_pct": 45.0,
    "manual_rainfall_mm": 2.0,
    "manual_evapotranspiration_mm": 5.0,
}


def read_rss(base_url: str) -> float | None:
    """The server's current RSS in MB, straight from its own /health/deep."""
    response = requests.get(f"{base_url}/api/v1/health/deep", timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("rss_mb")


def show(label: str, rss: float | None, extra: str = "") -> None:
    value = f"{rss:7.1f} MB" if rss is not None else "unavailable"
    print(f"  {label:<44} {value}   {extra}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--predictions", type=int, default=20,
        help="How many /predict calls to make in the burst step (default 20).",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    try:
        health = requests.get(f"{base}/api/v1/health", timeout=TIMEOUT_SECONDS)
        health.raise_for_status()
    except Exception as exc:
        print(f"Could not reach {base}/api/v1/health — is the server running?\n  {exc}")
        return 1

    info = health.json()
    print(f"Target:      {base}")
    print(f"Environment: {info['environment']}")
    print(f"Model:       {info['model_version']}")
    print()
    print("  step                                         RSS")
    print("  " + "-" * 64)

    # Baseline: the process has answered only /health, which touches nothing.
    show("baseline (after /health)", read_rss(base))

    meta = requests.get(f"{base}/api/v1/meta", timeout=TIMEOUT_SECONDS)
    meta.raise_for_status()
    show("after /api/v1/meta", read_rss(base), f"HTTP {meta.status_code}, {len(meta.json()['districts'])} districts")

    # First /predict is the expensive one: it lazily loads the model and
    # (where the model is under the SHAP cap) builds the TreeExplainer.
    first = requests.post(f"{base}/api/v1/predict", json=SAMPLE_PREDICTION, timeout=TIMEOUT_SECONDS)
    first.raise_for_status()
    body = first.json()
    explained = "explanation: present" if body.get("explanation") else "explanation: null"
    show("after 1st /api/v1/predict", read_rss(base), f"HTTP {first.status_code}, {explained}")

    for _ in range(max(0, args.predictions - 1)):
        requests.post(f"{base}/api/v1/predict", json=SAMPLE_PREDICTION, timeout=TIMEOUT_SECONDS).raise_for_status()
    steady = read_rss(base)
    show(f"after {args.predictions} /api/v1/predict calls", steady, "steady state")

    print()
    recommendation = body.get("irrigation_recommendation_mm")
    print(f"Sample recommendation: {recommendation} mm  (SYNTHETIC research data)")
    print(json.dumps({"steady_rss_mb": steady, "target": base}, indent=2))

    if steady is not None:
        headroom = 512 - steady
        print(f"\nAgainst the 512MB deployment ceiling: {headroom:.1f} MB headroom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
