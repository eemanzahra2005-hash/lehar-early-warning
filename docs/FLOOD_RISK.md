# Flood Risk Index — methodology (Phase 5.5)

> **See also:** [FLOOD_DL.md](FLOOD_DL.md) — LEHAR Phase 2.5 adds a flood
> **lead-time** model that predicts river discharge 1–3 days ahead and feeds
> it through this very same index and these very same bands, so an alert can
> fire before the flood rather than alongside it. The index below is
> unchanged by it: `GET /api/v1/flood/overview` and
> `/flood/district/{name}` behave exactly as they always have.

> **This is a heuristic research indicator, NOT an official flood warning.**
> It is a synthetic-project demo built from real GloFAS/Open-Meteo data, not
> a validated hydrological forecasting product. For real flood alerts in
> Pakistan, consult **NDMA** (National Disaster Management Authority) and
> **PMD** (Pakistan Meteorological Department). This disclaimer is shown
> verbatim in the API response (`disclaimer` field) and on every Flood Watch
> UI surface.

## Data sources (both real, live, no API key required)

1. **River discharge** — [Open-Meteo Flood API](https://flood-api.open-meteo.com/v1/flood),
   which serves [GloFAS](https://global-flood.emergencyresponsecoordinationcentre.europa.eu/)
   (Global Flood Awareness System) river-discharge model output. Queried per
   district with `daily=river_discharge&past_days=30&forecast_days=7`.
2. **Rainfall** — the existing Open-Meteo forecast integration
   (`app/services/weather.py`), reused for its 3-day `precipitation_sum`
   forecast — the flood API itself only returns discharge, no rainfall.

Both are fetched live on every cache miss; nothing here is fabricated or
backfilled (see CLAUDE.md rule 4). See `app/services/flood.py`'s module
docstring for the exact response shape confirmed by a real test call, and
its important caveat: district coordinates are city-center approximations
(the same synthetic lat/lon placeholders used for weather), so GloFAS
attaches each query to its *nearest modeled river reach* — for districts set
back from the main channel that may be a minor local stream rather than the
Indus/Kabul/Chenab mainstem. The numbers are real GloFAS output; treat them
as an approximate, city-level signal rather than a precise gauge reading.

## Derived discharge metrics

For each district's 37-day combined series (30 days past + today + 6 days
forecast):

```
discharge_baseline       = median(river_discharge over the past 30 days)
discharge_forecast_max   = max(river_discharge over the next 7 days, incl. today)
discharge_anomaly_ratio  = discharge_forecast_max / max(discharge_baseline, epsilon)
```

`epsilon = 0.01 m³/s` prevents a divide-by-zero on a bone-dry riverbed
(common for desert districts) — the ratio becomes a very large, correctly
alarming number instead of crashing.

## The 5 risk components (each clamped to `[0, 1]`)

| Component        | Formula                                   | Rationale |
|-------------------|-------------------------------------------|-----------|
| `discharge`       | `(anomaly_ratio - 1) / 1.5`               | 0 when forecast ≈ baseline (no anomaly); reaches 1.0 at a 2.5x baseline surge — a large but not extreme spike for a river. |
| `rain_3day`        | `3-day forecast cumulative rain / 100mm`  | 100mm over 3 days is a serious monsoon accumulation for most of Pakistan. |
| `rain_intensity`   | `max single forecast day's rain / 60mm`   | 60mm in a single day is heavy-rain-warning territory (roughly PMD's "heavy to very heavy rain" threshold). |
| `exposure`         | `river_exposure` from `backend/ml/districts.py` | Static per-district riverine/flash-flood exposure rating (0–1), documented per-district in that file — HIGH for Indus/Kabul mainstem districts, MODERATE for the Chenab/Ravi/Jhelum belt, LOW for barani/highland/desert districts. |
| `monsoon`          | `1.0` if the current month is Jul/Aug/Sep, else `0.3` | Pakistan's monsoon (and the bulk of its riverine flood risk) falls in Jul–Sep; a 0.3 floor (not 0) reflects that off-season flash floods and glacial-melt surges still happen. |

## Composite score

```
score = 100 * (
    W_DISCHARGE      * discharge +
    W_RAIN_3DAY      * rain_3day +
    W_RAIN_INTENSITY * rain_intensity +
    W_EXPOSURE       * exposure +
    W_MONSOON        * monsoon
)
```

Weights are environment-configurable (`backend/.env.example`,
`backend/app/config.py`), prefixed `FLOOD_W_*`, with these defaults:

| Env var                    | Default | Component        |
|-----------------------------|---------|-------------------|
| `FLOOD_W_DISCHARGE`         | 0.30    | `discharge`       |
| `FLOOD_W_RAIN_3DAY`         | 0.25    | `rain_3day`       |
| `FLOOD_W_RAIN_INTENSITY`    | 0.15    | `rain_intensity`  |
| `FLOOD_W_EXPOSURE`          | 0.20    | `exposure`        |
| `FLOOD_W_MONSOON`           | 0.10    | `monsoon`         |

With every component maxed out (`= 1.0`) and the default weights, the
theoretical maximum score is exactly `100.0`.

## Bands

| Score range   | Band    | Meaning |
|----------------|---------|---------|
| `< 35`         | `LOW`   | No elevated signal from live discharge/rain/exposure/season. |
| `35 – 60`      | `WATCH` | At least one input (surging discharge, heavy rain, high exposure, or monsoon season) is elevated — worth monitoring. |
| `> 60`         | `HIGH`  | Multiple inputs elevated together — the strongest heuristic signal this index produces. |

## Failure handling

Every external call (discharge fetch, rain forecast fetch) is wrapped
per-district: if either fails, that district's `status` becomes
`"unavailable"` in the API response instead of failing the whole request —
the same pattern as `GET /api/v1/map/overview` (`app/services/map_overview.py`).
The whole-response result is cached in memory for `FLOOD_CACHE_TTL_SECONDS`
(default 3600s / 1 hour) to stay a courteous, low-frequency caller of both
free upstream APIs.

## Cross-link with irrigation predictions

`POST /api/v1/predict` looks up the requested district's *current cached*
flood band (via `FloodService.get_band_for`, which never raises — if flood
data is unavailable for any reason, the lookup returns `None` and the
prediction proceeds completely unaffected). If the band is `HIGH`, the
response's `irrigation_recommendation_mm` is overridden to `0.0` with
`source="rule_flood_override"` and an explanatory `reason`; the model's
original (un-overridden) output is preserved in a new `model_raw_mm` field
so nothing is lost. The rationale: recommending irrigation during an active
high flood-risk window is actively counterproductive (fields are already at
risk of waterlogging/inundation), so the rule takes precedence over the
statistical model in that one specific case. This never blocks or slows
down a prediction — it's a same-cache, in-memory lookup, not an extra
network call.
