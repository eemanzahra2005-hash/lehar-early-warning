"""Download the REAL daily history the flood lead-time model trains on
(LEHAR Phase 2.5), one Parquet file per district.

    .venv\\Scripts\\python scripts\\data\\fetch_flood_history.py --limit 10
    .venv\\Scripts\\python scripts\\data\\fetch_flood_history.py

This is the ONE place in this project that downloads REAL measured/reanalysis
data rather than generating synthetic data. Everything the irrigation
RandomForest is trained on stays synthetic (CLAUDE.md rules 4 and 13); the
flood lead-time model is trained on the real series fetched here, and every
artifact derived from it says so rather than inheriting the synthetic label.

Data sources (both free, no API key)
------------------------------------
1. River discharge - Open-Meteo Flood API
   https://flood-api.open-meteo.com/v1/flood
   Serves GloFAS (Global Flood Awareness System, Copernicus Emergency
   Management Service) river-discharge model output. The historical range is
   requested with start_date/end_date. Variable: daily `river_discharge`
   (m3/s). This is the same upstream API app/services/flood.py already uses
   live for Flood Watch (see docs/FLOOD_RISK.md), asked for history instead
   of a 30-day window.

2. Precipitation and maximum temperature - Open-Meteo Historical Weather API
   https://archive-api.open-meteo.com/v1/archive
   ERA5 reanalysis. Variables: daily `precipitation_sum` (mm) and
   `temperature_2m_max` (C), requested with timezone=UTC so the daily
   aggregation boundary matches the discharge series' UTC days rather than
   107 different local midnights.

API terms (why this script is deliberately slow)
------------------------------------------------
Open-Meteo is free for NON-COMMERCIAL use and its data is published under
CC BY 4.0, with a fair-use limit on the free tier (roughly 10,000 API calls
per day, 5,000 per hour and 600 per minute at the time of writing - see
https://open-meteo.com/en/terms). LEHAR is a student research project, which
is exactly that non-commercial use.

The limits are counted in WEIGHTED calls, not in requests: a request costs
roughly (number of variables x number of days / 336) units, so one 30-year
daily pull is worth far more than one "call". Measured against that budget,
this script costs about `days / 112` units per district - three variables
across two endpoints - which for all 107 districts works out at:

    1997-2026 (~10,850 days)  ~10,400 units  - over the DAILY budget
    2010-2026 (~6,100 days)   ~5,800 units   - over one HOURLY budget
    2019-2026 (~2,818 days)   ~2,700 units   - fits

That is not a theoretical concern: a first attempt at the full 1997-onward
history for all 107 districts started returning HTTP 429 at district 24.
So the default --start stays 1984-01-01 (ask for everything; the provider
decides what it has), and the run that actually produced this project's
dataset passed `--start 2019-01-01` (resumed after an interruption with
`--end 2026-09-18 --sleep 2` so every district shares one end date), which
is recorded in docs/FLOOD_DL.md along with what that window does and does
not cover.

--sleep is the knob: it is the pause between individual API calls, so the
whole run is paced rather than bursted. Please keep it that way. A 429 is
backed off from, at increasing intervals, rather than hammered.

Attribution, reproduced in docs/FLOOD_DL.md, in the model card and in the
response of GET /api/v1/flood/forecast/{district}:

    Weather data by Open-Meteo.com (CC BY 4.0).
    River discharge from GloFAS / Copernicus Emergency Management Service,
    served via Open-Meteo.

Output
------
data/flood_history/<district_code>.parquet, one row per UTC day with columns:

    date                 datetime64[ns]  the UTC day
    river_discharge_m3s  float64         GloFAS daily mean discharge
    precipitation_mm     float64         ERA5 daily precipitation sum
    temperature_max_c    float64         ERA5 daily maximum 2 m temperature

plus data/flood_history/_manifest.json recording, per district, what was
fetched and when. Leading days with no discharge at all are trimmed: GloFAS
coverage does not reach 1984 for every river reach, so each district starts
at ITS OWN earliest available day rather than at a date assumed for all.

Resumable: a district whose Parquet file already reaches the requested end
date is skipped. Pass --force to refetch everything.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.districts import DISTRICTS, district_code  # noqa: E402

FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"
ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"

OUTPUT_DIR = PROJECT_ROOT / "data" / "flood_history"
MANIFEST_PATH = OUTPUT_DIR / "_manifest.json"

# GloFAS's nominal start on Open-Meteo. Reaches with shorter coverage simply
# return nulls before their own first day, which _trim_leading_gap drops.
DEFAULT_START_DATE = "1984-01-01"

# The archive API is reanalysis and lags real time by about 5 days; asking
# for days it has not produced yet returns nulls rather than an error.
ARCHIVE_LAG_DAYS = 6

# A 429 here means "you are inside the free tier's fair-use window" — the
# right answer is to wait properly, not to retry three times in 30 seconds
# and give up. Backoff is linear (30 s, 60 s, ... 150 s), which is enough to
# clear Open-Meteo's per-MINUTE bucket without abandoning a district.
MAX_ATTEMPTS = 6
RETRY_BACKOFF_SECONDS = 30.0

# The per-HOUR bucket is a different matter: no amount of short backoff
# clears it, and Open-Meteo says so in the response body. The only polite
# answer is to stop until the hour rolls over, so that is what this does
# rather than burning the remaining attempts against a closed door. The two
# endpoints have SEPARATE hourly budgets (measured: the archive API was
# exhausted while the flood API still answered 200), so one being spent does
# not stop the other.
HOURLY_LIMIT_MARKER = "hourly api request limit exceeded"
# Extra seconds past the hour boundary, so a slightly-out-of-step server
# clock cannot land the retry in the last second of the exhausted hour.
HOUR_RESET_GRACE_SECONDS = 45
# How many hour-boundary waits one request may sit through before giving up.
MAX_HOURLY_WAITS = 3


def _seconds_until_next_hour() -> float:
    now = datetime.now(timezone.utc)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds() + HOUR_RESET_GRACE_SECONDS

ATTRIBUTION = (
    "Weather data by Open-Meteo.com (CC BY 4.0). River discharge from GloFAS / "
    "Copernicus Emergency Management Service, served via Open-Meteo."
)


def _get_json(url: str, params: dict, timeout: float) -> dict:
    """One polite GET with retries. 5xx and 429 are retried with a linear
    backoff (a free API that says "slow down" is told yes); anything else
    raises immediately, so a genuine mistake - a bad variable name, a date
    outside the supported range - fails loudly instead of being retried four
    times and then quietly dropped."""
    last_error = ""
    hourly_waits = 0
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code == 429 and HOURLY_LIMIT_MARKER in response.text.lower():
                # The hourly budget, not the minute one. Wait it out rather
                # than spending attempts, and don't count this as an attempt.
                if hourly_waits >= MAX_HOURLY_WAITS:
                    raise RuntimeError(f"{url}: hourly API limit still exhausted after {hourly_waits} hour(s) of waiting.")
                hourly_waits += 1
                wait = _seconds_until_next_hour()
                print(
                    f"      hourly API limit reached — waiting {wait / 60:.1f} min for the next hour "
                    f"(wait {hourly_waits}/{MAX_HOURLY_WAITS})",
                    flush=True,
                )
                time.sleep(wait)
                attempt -= 1
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
            else:
                # 4xx other than rate limiting: the request itself is wrong.
                raise RuntimeError(
                    f"{url} rejected the request: HTTP {response.status_code} {response.text[:200]}"
                )
        if attempt < MAX_ATTEMPTS:
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"      retry {attempt}/{MAX_ATTEMPTS - 1} after {last_error} - waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"{url} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def fetch_discharge(lat: float, lon: float, start: str, end: str, timeout: float) -> pd.DataFrame:
    """GloFAS daily river discharge (m3/s) for one coordinate."""
    payload = _get_json(
        FLOOD_API_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge",
            "start_date": start,
            "end_date": end,
        },
        timeout,
    )
    daily = payload["daily"]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(daily["time"]),
            "river_discharge_m3s": pd.to_numeric(pd.Series(daily["river_discharge"]), errors="coerce"),
        }
    )


def fetch_weather(lat: float, lon: float, start: str, end: str, timeout: float) -> pd.DataFrame:
    """ERA5 daily precipitation sum (mm) and maximum temperature (C)."""
    payload = _get_json(
        ARCHIVE_API_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_sum,temperature_2m_max",
            "start_date": start,
            "end_date": end,
            # UTC, not "auto": the discharge series is on UTC days, and two
            # series aggregated on different midnights cannot be joined by
            # date without quietly shifting one against the other.
            "timezone": "UTC",
        },
        timeout,
    )
    daily = payload["daily"]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(daily["time"]),
            "precipitation_mm": pd.to_numeric(pd.Series(daily["precipitation_sum"]), errors="coerce"),
            "temperature_max_c": pd.to_numeric(pd.Series(daily["temperature_2m_max"]), errors="coerce"),
        }
    )


def _trim_leading_gap(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the leading run of days that have no discharge value.

    GloFAS coverage on Open-Meteo does not reach 1984 for every river reach
    - some start in the mid-1990s. Rather than assume one start date for all
    107 districts, each district keeps everything from ITS OWN first real
    reading onward. Gaps in the MIDDLE of a series are deliberately left in
    place as NaN: the dataset builder needs to see them so it can refuse to
    build a training window that spans one (see ml/flood_dl/dataset.py)."""
    valid = frame["river_discharge_m3s"].notna()
    if not valid.any():
        return frame.iloc[0:0]
    return frame.loc[valid.idxmax() :].reset_index(drop=True)


def build_district_frame(params: dict, start: str, end: str, timeout: float, sleep: float) -> pd.DataFrame:
    discharge = fetch_discharge(params["lat"], params["lon"], start, end, timeout)
    time.sleep(sleep)
    weather = fetch_weather(params["lat"], params["lon"], start, end, timeout)

    merged = discharge.merge(weather, on="date", how="inner").sort_values("date").reset_index(drop=True)
    return _trim_leading_gap(merged)


def _existing_is_current(path: Path, end: str) -> bool:
    """True when an already-downloaded file reaches the requested end date,
    which is what makes this script resumable - a rerun after a crash
    re-fetches only the districts that are actually missing."""
    if not path.exists():
        return False
    try:
        existing = pd.read_parquet(path, columns=["date"])
    except Exception:
        return False
    if existing.empty:
        return False
    return existing["date"].max().date() >= date.fromisoformat(end)


def _read_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"attribution": ATTRIBUTION, "districts": {}}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"attribution": ATTRIBUTION, "districts": {}}


def _write_manifest(manifest: dict) -> None:
    manifest["attribution"] = ATTRIBUTION
    manifest["sources"] = {"river_discharge": FLOOD_API_URL, "weather": ARCHIVE_API_URL}
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--start", default=DEFAULT_START_DATE, help=f"first day to request (default {DEFAULT_START_DATE})"
    )
    parser.add_argument("--end", default=None, help="last day to request (default: today - 6 days, the archive lag)")
    parser.add_argument("--limit", type=int, default=None, help="only fetch the first N districts (validation run)")
    parser.add_argument("--sleep", type=float, default=1.5, help="seconds to sleep between API calls (default 1.5)")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-request timeout in seconds")
    parser.add_argument("--force", action="store_true", help="refetch districts that already have a current file")
    args = parser.parse_args()

    end = args.end or (date.today() - timedelta(days=ARCHIVE_LAG_DAYS)).isoformat()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest()

    names = list(DISTRICTS)[: args.limit] if args.limit else list(DISTRICTS)
    print(f"LEHAR Phase 2.5 - flood history fetch: {len(names)} district(s), {args.start} to {end}")
    print(f"  {ATTRIBUTION}")
    print(f"  Free NON-COMMERCIAL use; sleeping {args.sleep}s between calls to stay a polite caller.\n", flush=True)

    fetched = skipped = failed = 0
    for index, name in enumerate(names, start=1):
        code = district_code(name)
        path = OUTPUT_DIR / f"{code}.parquet"
        prefix = f"[{index:3d}/{len(names)}] {name:<22}"

        if not args.force and _existing_is_current(path, end):
            print(f"{prefix} already current - skipped", flush=True)
            skipped += 1
            continue

        try:
            frame = build_district_frame(DISTRICTS[name], args.start, end, args.timeout, args.sleep)
        except Exception as exc:  # one bad district must never end the run
            print(f"{prefix} FAILED: {exc}", flush=True)
            failed += 1
            manifest["districts"][code] = {"district": name, "status": "failed", "error": str(exc)[:300]}
            _write_manifest(manifest)
            time.sleep(args.sleep)
            continue

        if frame.empty:
            print(f"{prefix} no river discharge available at this coordinate - skipped", flush=True)
            manifest["districts"][code] = {"district": name, "status": "empty", "rows": 0}
            _write_manifest(manifest)
            failed += 1
            time.sleep(args.sleep)
            continue

        frame.to_parquet(path, index=False)
        first, last = frame["date"].min().date(), frame["date"].max().date()
        missing = int(frame["river_discharge_m3s"].isna().sum())
        print(
            f"{prefix} {len(frame):>6} rows  {first} -> {last}  "
            f"discharge median {frame['river_discharge_m3s'].median():.2f} m3/s  gaps {missing}",
            flush=True,
        )
        manifest["districts"][code] = {
            "district": name,
            "province": DISTRICTS[name]["province"],
            "status": "ok",
            "rows": int(len(frame)),
            "first_date": first.isoformat(),
            "last_date": last.isoformat(),
            "missing_discharge_days": missing,
            "lat": DISTRICTS[name]["lat"],
            "lon": DISTRICTS[name]["lon"],
        }
        _write_manifest(manifest)
        fetched += 1
        time.sleep(args.sleep)

    print(f"\nDone: {fetched} fetched, {skipped} already current, {failed} failed/empty.")
    print(f"Output: {OUTPUT_DIR}")
    return 1 if failed and not fetched else 0


if __name__ == "__main__":
    raise SystemExit(main())
