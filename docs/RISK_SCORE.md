# Farm Risk Score — methodology (Phase 6)

> **This is a transparent decision-support heuristic, NOT a validated
> agronomic index.** It is a simple, documented arithmetic formula over
> real input values — not a statistical model, not a learned score, and
> not agronomic advice. It exists to give a quick, explainable "how
> stressed is this field right now?" signal alongside the ML irrigation
> recommendation. This disclaimer is shown verbatim wherever the score
> appears in the UI.

## Irrigation stress, not flood risk

This is the opposite extreme from the [Flood Risk Index](FLOOD_RISK.md):
the Farm Risk Score measures **dryness / irrigation stress** — how much a
field is likely to be under-watered right now. The Flood Risk Index
measures the opposite (too much water, riverine/monsoon flooding). A field
can score HIGH on one and LOW on the other; they are computed completely
independently and shown as separate badges in the UI ("Irrigation stress"
vs "Flood Watch") so they are never confused.

## Inputs

All five inputs are values already shown elsewhere in the app — nothing
here is fetched or computed specially for the risk score:

| Input                    | Source                                          |
|---------------------------|--------------------------------------------------|
| `soil_moisture_pct`       | User input (predict form) or default field conditions (map) |
| `evapotranspiration_mm`   | Live/manual weather (`weather_used`)              |
| `temperature_c`           | Live/manual weather (`weather_used`)              |
| `canal_flow_cusecs`       | User input (predict form) or district baseline (map) |
| `rainfall_mm`              | Live/manual weather (`weather_used`)              |

## The 5 components (each clamped to `[0, 1]`)

| Component          | Formula                              | Rationale |
|---------------------|----------------------------------------|-----------|
| `moisture_deficit`  | `(35 - soil_moisture_pct) / 25`        | 0 at 35% soil moisture (comfortably wet for most of this project's crops), reaches 1.0 at 10% (very dry). |
| `et0_demand`        | `(evapotranspiration_mm - 5) / 5`      | 0 at 5mm/day ET0 (moderate demand), reaches 1.0 at 10mm/day (very high atmospheric water demand — hot, dry, windy conditions). |
| `heat_stress`       | `(temperature_c - 35) / 10`            | 0 at or below 35°C, reaches 1.0 at 45°C — extreme heat accelerates crop water loss beyond what ET0 alone captures. |
| `water_scarcity`    | `(300 - canal_flow_cusecs) / 300`      | 0 at 300 cusecs (a solid canal-command supply), reaches 1.0 at 0 cusecs (no canal water available, e.g. barani/tubewell-dependent districts — see `ml/districts.py`). |
| `rain_relief`       | `rainfall_mm / 20`                     | 0 with no rain, reaches 1.0 at 20mm — recent/forecast rain that materially reduces irrigation need. This is the only component that's **subtracted**, not added. |

## Composite score

```
score = 100 * clamp01(
    W_MOISTURE_DEFICIT * moisture_deficit +
    W_ET0_DEMAND        * et0_demand +
    W_HEAT_STRESS       * heat_stress +
    W_WATER_SCARCITY    * water_scarcity -
    W_RAIN_RELIEF        * rain_relief
)
```

The outer `clamp01` runs on the *weighted sum* (not just each term
individually) — so heavy rain can pull an otherwise-elevated score all the
way down to 0, and the score never goes negative or above 100.

Weights are environment-configurable (`backend/.env.example`,
`backend/app/config.py`), prefixed `RISK_W_*`, with these defaults:

| Env var                  | Default | Component          |
|----------------------------|---------|-----------------------|
| `RISK_W_MOISTURE_DEFICIT`  | 0.35    | `moisture_deficit`   |
| `RISK_W_ET0_DEMAND`        | 0.20    | `et0_demand`         |
| `RISK_W_HEAT_STRESS`       | 0.15    | `heat_stress`        |
| `RISK_W_WATER_SCARCITY`    | 0.15    | `water_scarcity`     |
| `RISK_W_RAIN_RELIEF`       | 0.15    | `rain_relief` (subtracted) |

With every additive component maxed out (`= 1.0`) and zero rain relief, the
default weights (`0.35 + 0.20 + 0.15 + 0.15 = 0.85`) cap the score at
`85.0`, not `100.0` — reaching the full `0..100` range would require custom
weights summing to `1.0`. This is intentional with the reference defaults:
it leaves headroom so no single component alone can push a field all the
way to a HIGH score, and reserves `clamp01` on the weighted sum as a guard
for custom weight configurations, not something the reference defaults rely
on to stay in range.

## Bands

| Score range   | Band       | Meaning |
|----------------|------------|---------|
| `< 34`         | `LOW`      | Field is not showing significant irrigation stress signals. |
| `34 – 66`      | `MODERATE` | At least one input (low moisture, high ET0, heat, scarce canal supply) is elevated — worth planning around. |
| `> 66`         | `HIGH`     | Multiple stress inputs elevated together — the strongest heuristic signal this score produces. |

## Where it's computed

- `POST /api/v1/predict` — computed from the request's real inputs
  (`soil_moisture_pct`, `canal_flow_cusecs`) and the weather actually used
  for that prediction (live or manual), **regardless of prediction source**
  (model, sensor-fault fallback, or flood override) — it's pure arithmetic
  on inputs the user already sees, not dependent on the ML model running.
  Returned in the `risk` field and stored on the `prediction_logs` row
  (`risk_score`, `risk_band`, added in Phase 6 via an additive SQLite
  `ALTER TABLE` — see `app/db.py`).
- `GET /api/v1/map/overview` — computed per district using the same
  documented default field conditions as the map's recommendation
  (`soil_moisture_pct=25%`, each district's baseline canal flow), so it's
  directly comparable across all 107 districts on the choropleth/side panel.

## Failure handling

The score is pure arithmetic with no external I/O — there is no network
call to fail, so in practice `risk` is always populated on a successful
`/predict` or map-overview response. It is still typed as nullable in the
API response for forward compatibility and to keep the "never let a
secondary feature break the primary response" contract consistent with how
`explanation`/`confidence` (SHAP-based, and *can* fail — see
`app/services/explain.py`) and the Flood Risk Index are handled elsewhere
in this app.
