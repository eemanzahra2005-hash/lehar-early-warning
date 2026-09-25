# Live soil moisture — source, mapping, and honest limits (Phase 16)

> **A live soil moisture value in this app is a weather-model estimate, not a
> measurement.** It comes from Open-Meteo's forecast model for a grid cell
> around the district's main city. There is no sensor in your field, and the
> model knows nothing about irrigation you have applied. Every surface says
> so: the Predict page shows *"model-estimated — Open-Meteo, not a field
> sensor"*, the API returns `soil_moisture_source: "live (Open-Meteo model
> estimate)"`, and the assistant receives the same label. The feature is
> **off by default**; manual soil moisture works exactly as before.

## 1. Where the value comes from

| | |
|---|---|
| API | The same Open-Meteo forecast API already used for weather (`https://api.open-meteo.com/v1/forecast`), no key |
| Location | The district's `lat`/`lon` in `backend/ml/districts.py` (its main city) |
| Variables | `hourly=soil_moisture_1_to_3cm,soil_moisture_3_to_9cm,soil_moisture_9_to_27cm` |
| Unit | `m³/m³` (volumetric water fraction) — confirmed by a real call for Multan on 2026-09-15 before any code was written against it |
| Other params | `timezone=auto` (timestamps are district-local), `past_days=1`, `forecast_days=1` |
| Which hour | The most recent hour **at or before the current district-local time** where all three layers have a value. The hourly arrays also contain the rest of today's *forecast* hours; those are skipped. `past_days=1` guarantees an earlier complete hour exists, e.g. just after local midnight. |
| Timeout / retries / cache | Identical to weather: `WEATHER_TIMEOUT_SECONDS`, up to 2 retries on 5xx, in-memory per-district cache for `WEATHER_CACHE_TTL_SECONDS`. No new environment variables. |

Code: `backend/app/services/weather.py` (`WeatherService.fetch_soil_moisture`)
for the request, `backend/app/services/soil.py` for the pure maths below.

## 2. Step 1 — depth-weighted root-zone average

```
θ_root = (2·θ[1–3 cm] + 6·θ[3–9 cm] + 18·θ[9–27 cm]) / 26        (m³/m³)
```

The weights are the layer thicknesses in centimetres (`LAYER_THICKNESS_CM`).
Volumetric content × thickness is the depth of water a layer holds, so
`θ_root` is the total water in the 1–27 cm profile divided by its 26 cm
depth. A plain mean of the three values would let the 2 cm surface skin
count as much as the 18 cm layer beneath it. That skin dries out within
hours of sun and wets up from a light shower, while most shallow crop roots
sit in the deeper layer.

## 3. Step 2 — mapping into the model's `soil_moisture_pct` space

### What `soil_moisture_pct` means in training

This was read from the code, not assumed:

| Where | What it says |
|---|---|
| `backend/ml/generate_data.py` | `soil_moisture_pct = clip(20 + 0.15·rain + 0.02·canal_flow − 1.1·ET0 + noise, 5, 60)`. Synthetic. No unit is stated, and nothing refers to field capacity or soil type. |
| `backend/ml/districts.py` | No soil-type, field-capacity, or wilting-point parameter for any of the 107 districts. |
| `docs/DATA_VALIDATION.md` | Bounded `0–100`, described as a "volumetric/relative sensor reading, 0-100%". |
| Target formula + `docs/RISK_SCORE.md` | Irrigation is needed below 35%. 35% is "comfortably wet for most of this project's crops" and 10% is "very dry". |
| Production model `v20260812T205121116100Z`, `reference_stats.json` | Real training values: mean **22.5**, std 5.1, min 6.05, max 44.96. |

### Choice: volumetric percent

```
soil_moisture_pct = clamp(100 × θ_root, 0, 100), rounded to 0.1
```

This is implemented as `to_soil_moisture_pct()` with the named constant
`M3_PER_M3_TO_PCT = 100.0`. Why volumetric % rather than percent of field
capacity:

1. **The code's thresholds only make sense as volumetric %.** 35% volumetric
   is roughly field capacity for loamy soils (typically ~0.25–0.35 m³/m³),
   so "comfortably wet, no irrigation needed" fits. Read as *percent of field
   capacity*, 35% would be serious water stress, well past the ~50% depletion
   point where irrigation is usually triggered. That contradicts
   `RISK_SCORE.md`'s "comfortably wet".
2. **The training distribution matches real volumetric values.** The training
   mean of 22.5% sits where Open-Meteo's volumetric estimates for the
   irrigated plains actually are. For example, Multan at 06:00 local on
   2026-09-15 read 0.193 / 0.213 / 0.230 m³/m³, giving a root zone of 0.2232
   and **22.3%**.
3. **Percent of field capacity would need data this project doesn't have.**
   It needs a field-capacity constant per district, and `districts.py` has
   none. Using it would mean inventing 107 new synthetic soil constants and
   making every live value depend on them. A pure unit conversion adds no
   invented numbers.

The clamp matches the API's existing `0–100` bound on a manual value, so a
live value can never be something `POST /predict` would reject.

If a future dataset redefines soil moisture as percent of field capacity,
`to_soil_moisture_pct()` is the single function to change, together with a
per-district field-capacity table in `districts.py`.

## 4. Limits — read before trusting a live value

- **It is not your field.** It is a model estimate for a grid cell around the
  district's main city, and soils vary a lot within one district.
- **It doesn't know about irrigation.** A field watered yesterday will be
  wetter than the estimate. If you have a real reading, enter it manually;
  that is still the default.
- **Shallow profile only (1–27 cm).** Deeper-rooted crops such as cotton and
  sugarcane draw water from below this depth.
- **Outside the training range, the model can't extrapolate.** The model was
  trained on synthetic values between ~6% and ~45%. Beyond that (e.g. very
  dry desert districts, or waterlogged soil) the RandomForest's output
  plateaus at the edge of what it saw.
- **History records the value, not its source.** `prediction_logs` stores the
  soil moisture actually used, but not whether it was live or manual.

## 5. API

### `POST /api/v1/predict` (additive)

- New optional request field `use_live_soil` (default `false`). Requests
  without it behave exactly as before.
- `soil_moisture_pct` is still required. It is the manual value, and the
  fallback when the live fetch fails.
- When a live value is used, that single value feeds the ML model, the Farm
  Risk Score, the sensor-fault fallback rule, `inputs_used`, and
  `prediction_logs`.

New response fields, always present:

```json
{
  "soil_moisture_used": 22.3,
  "soil_moisture_source": "live (Open-Meteo model estimate)",
  "soil_moisture_layers": {
    "soil_moisture_1_to_3cm": 0.193,
    "soil_moisture_3_to_9cm": 0.213,
    "soil_moisture_9_to_27cm": 0.23,
    "root_zone": 0.2232,
    "unit": "m³/m³",
    "observed_at": "2026-09-15T06:00"
  },
  "soil_moisture_note": null
}
```

For a manual prediction, `soil_moisture_source` is `"manual"` and
`soil_moisture_layers` is `null`.

**Fallback.** If `use_live_soil` is `true` but the fetch fails (timeout,
provider error, or no data), the prediction still succeeds with the manual
value. `soil_moisture_source` is `"manual"`, `soil_moisture_layers` is `null`,
and `soil_moisture_note` says what happened, e.g. *"Live soil moisture
unavailable (Weather provider request timed out.) — used the manual value
instead."* Unlike live weather, a live soil failure never fails the request.

### `GET /api/v1/soil-moisture?district=Multan`

Returns the same reading (`soil_moisture_pct`, `source`, `label`, `layers`) so
the Predict page can show the value before a prediction runs. It fails exactly
like `GET /weather`: 400 for an unknown district, 502/504 when the provider
fails.

### Assistant

- `live_soil_moisture` — the district's live value, with `source`, the
  model-estimate `note`, and the raw `layers`. It is omitted entirely if the
  fetch fails.
- `irrigation_recommendation.soil_moisture_source` — the assistant's own
  district recommendation still uses the Map page's fixed 25% default, now
  explicitly labelled `"default assumption (not measured)"`.
- `this_prediction` — sent from the Predict page's "Explain in Urdu" button,
  it carries the prediction's `soil_moisture_used` / `soil_moisture_source`.

## 6. Predict page behaviour

- **Toggle ON:** the page fetches `GET /soil-moisture` for the selected
  district. The slider shows that value, greyed and read-only, labelled
  *"model-estimated — Open-Meteo, not a field sensor"*. The value refreshes
  when the district changes.
- **Toggle OFF:** the manual slider comes back with the value you last set.
- **Live fetch fails:** the toggle switches itself off, the manual slider
  comes back, and a visible notice explains why. Prediction is never
  blocked.
- **After a prediction:** the form mirrors what the server actually used.
  "Save as field" always saves your manual value, never a live estimate.
