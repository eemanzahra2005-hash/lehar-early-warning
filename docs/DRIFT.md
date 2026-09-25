# Data-drift monitoring — PSI methodology (Phase 8)

> **PSI (Population Stability Index) is a simple, widely-used drift
> heuristic — NOT a rigorous statistical test**, and the 0.1 / 0.25
> warn/alert thresholds below are common industry rules of thumb (most
> often cited from credit-risk-scoring literature) — **not scientifically
> validated for irrigation/weather data specifically**. Treat a "warning"
> or "significant drift" band as a prompt to look closer, not as proof the
> model is wrong.

## What's being compared

- **Reference (baseline)**: the currently-active production model's
  training data, summarized at training time into
  `backend/ml/model/<version>/reference_distribution.json`
  (`ml/pipeline.py`'s `compute_reference_distribution()`) — a 20-bin
  histogram + mean/std/min/max per numeric feature, and raw value
  frequencies per categorical feature, computed on the TRAINING split
  only (never the test split).
- **Current (live)**: the last `DRIFT_WINDOW` real prediction inputs from
  the `prediction_logs` table (`app/db.py`) — the same weather/soil/canal
  values already logged on every `POST /api/v1/predict` call, regardless
  of prediction source (model, sensor-fault fallback, flood override).

8 features are compared, exactly matching what's logged per prediction:

| Numeric                                                                 | Categorical            |
|--------------------------------------------------------------------------|--------------------------|
| `temperature_c`, `humidity_pct`, `rainfall_mm`, `evapotranspiration_mm`, `canal_flow_cusecs`, `soil_moisture_pct` | `district`, `crop_type` |

This is a deliberate subset of the model's full 11 training features — it
excludes `was_imputed`/`month`/`day_of_year`, which are training-time
engineering columns with no live counterpart to compare against.

## The PSI formula

For each feature, both windows are expressed as proportions over the same
set of bins (the reference's own 20 histogram bins for numeric features;
the union of categories seen in either window for `district`/`crop_type`):

```
PSI = sum over bins of:  (current_pct - reference_pct) * ln(current_pct / reference_pct)
```

Each bin's raw COUNT (not proportion) gets Laplace ("add-one") smoothing
before normalizing — `(count + 1) / (total + n_bins)` — rather than a fixed
epsilon floor on the proportion. This matters at this app's realistic
window sizes: `DRIFT_WINDOW`/`DRIFT_MIN_SAMPLES` default to 200/50, and a
live window that small, split across the reference's 20 fixed bins,
regularly lands **zero** samples in a tail bin purely by chance (average
2.5-10 samples/bin) even with no real drift. Flooring that bin's
proportion at a tiny fixed epsilon made it look dramatically different
from a reference bin with a real-but-small share, inflating PSI on pure
sampling noise — verified empirically: a 60-sample resample of the exact
same population produced PSI as high as ~0.6 (comfortably into
"significant_drift") with fixed-epsilon flooring, versus a real,
comfortably-"stable" score with count-based Laplace smoothing (see
`backend/tests/test_drift.py`). Current numeric values outside the
reference's original min/max are **clipped into the outermost bin, not
dropped** — a real shift beyond the training range should still show up as
drift, not be silently discarded.

**Caveat, honestly stated**: smoothing reduces but does not eliminate
small-sample noise. Right at `DRIFT_MIN_SAMPLES` (the minimum window this
endpoint will compute PSI on at all), an isolated `warning` band with no
other corroborating signal is still plausibly noise, not real drift —
treat `significant_drift` (a much larger gap) as the more trustworthy
signal at small sample counts, and revisit once `samples_available`
approaches the full `DRIFT_WINDOW`.

## Bands

| PSI range      | Band                | Meaning (rule of thumb) |
|------------------|----------------------|--------------------------|
| `< 0.1`          | `stable`             | No meaningful shift from training data. |
| `0.1 – 0.25`     | `warning`            | Some shift — worth a look, not necessarily action. |
| `>= 0.25`        | `significant_drift`  | Substantial shift — the live input distribution looks meaningfully different from what the model was trained on. |

Env-configurable (`backend/.env.example`, `backend/app/config.py`):

| Env var              | Default | Meaning |
|------------------------|---------|-----------|
| `DRIFT_WINDOW`         | 200     | How many of the most recent `prediction_logs` rows to compare against the baseline. |
| `DRIFT_MIN_SAMPLES`    | 50      | Below this many available rows, the endpoint reports `insufficient_data` instead of a PSI computed on too little to mean anything. |
| `DRIFT_PSI_WARN`       | 0.1     | PSI at/above this -> `warning` band. |
| `DRIFT_PSI_ALERT`      | 0.25    | PSI at/above this -> `significant_drift` band. |

**Overall status = the worst individual feature's band.** One feature in
`significant_drift` is enough to make the whole report `significant_drift`,
even if every other feature is `stable`.

## The `insufficient_data` state

Returned honestly (real `samples_available` count, empty `features` list —
never a fabricated PSI) whenever either is true:

- Fewer than `DRIFT_MIN_SAMPLES` prediction_logs rows exist yet (a fresh
  database, or a quiet app).
- The active production model version has no `reference_distribution.json`
  (e.g. a legacy pre-Phase-8 model version that was never retrained since).

`reference_model_version` is always the real, currently-active model
version string in every response — even in the `insufficient_data` case —
so the UI can always say *which* model's baseline (or lack of one) is being
described.

## Endpoint

`GET /api/v1/monitoring/drift` — no auth required (read-only, same
transparency stance as `GET /api/v1/models`):

```json
{
  "status": "stable | warning | significant_drift | insufficient_data",
  "window_used": 200,
  "samples_available": 187,
  "reference_model_version": "v20260812T205121116100Z",
  "features": [
    {
      "name": "temperature_c",
      "psi": 0.0421,
      "band": "stable",
      "reference_hist": { "edges": [...21 floats...], "counts": [...20 ints...] },
      "current_hist":   { "edges": [...21 floats...], "counts": [...20 ints...] }
    }
  ]
}
```

`features` is empty when `status == "insufficient_data"`.

## Where it's computed / served

- `app/services/drift.py`'s `DriftService.compute()` — reads
  `reference_distribution.json` fresh from the ACTIVE model version's
  folder on every call (never cached across a promote/rollback — see
  `app/dependencies.py`'s `_drift_service_for`, cached per `ModelService`
  identity, so a hot-reloaded model naturally invalidates it), plus the
  last `DRIFT_WINDOW` rows of `prediction_logs`.
- `app/routers/monitoring.py` — `GET /api/v1/monitoring/drift`.
- `frontend/js/views/monitoring.js` — status banner (icon + label + color,
  never color alone — same accessibility rule as the Flood Watch/Farm Risk
  bands), a per-feature PSI bar chart with the warn/alert threshold lines
  marked, and a click-through reference-vs-current histogram overlay per
  feature.

## Failure handling

Reading a malformed/corrupt `reference_distribution.json` is caught and
logged, treated the same as a missing one (`insufficient_data`) rather than
a `500` — this endpoint never crashes the Monitoring page.
