# Flood lead-time model (LEHAR Phase 2.5)

> **Research indicator, not an official forecast.**
> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> GloFAS and Pakistan's NDMA/PMD/PDMA remain the authoritative sources for
> flood warning. Everything on this page is a student research project's
> experiment, and every surface that shows one of these forecasts says so.

## The idea

[Flood Watch](FLOOD_RISK.md) answers **"how bad does the river look right
now?"** — it reads today's GloFAS discharge and today's rain forecast and
scores the result. That is useful, but it is a *nowcast*: by the time the
Flood Risk Index turns red, the flood wave is already on its way.

This phase adds the other half, the one a tsunami warning system has: a
model that predicts **where the river will be in 1, 2 and 3 days**, so an
alert can fire *before* the water arrives. The prediction is then pushed
through the *same* Flood Risk Index and the *same* band thresholds, so a
predicted level 3 means exactly what an observed level 3 means — one day
earlier.

The irrigation RandomForest is untouched by all of this. It is a separate
model, for a separate question, and it remains trained on synthetic data.

## This is the one model trained on REAL data

Everything else in LEHAR is trained on synthetic research data (CLAUDE.md
rules 4 and 13). This model is not. It is trained on:

| Variable | Source | What it actually is |
|---|---|---|
| `river_discharge` (m³/s) | [Open-Meteo Flood API](https://flood-api.open-meteo.com/v1/flood) | [GloFAS](https://global-flood.emergencyresponsecoordinationcentre.europa.eu/) (Global Flood Awareness System, Copernicus EMS) river-discharge model output |
| `precipitation_sum` (mm) | [Open-Meteo Historical Weather API](https://archive-api.open-meteo.com/v1/archive) | ERA5 reanalysis |
| `temperature_2m_max` (°C) | same | ERA5 reanalysis |

Because the distinction matters more than a line in a document, it travels
with the artifact: `metrics.json`, the API response of
`GET /api/v1/flood/forecast/{district}`, and every FLOOD_FORECAST alert
message all state that this model is trained on real data **and** that
LEHAR's irrigation model separately is not.

### Attribution

Required by both providers, and reproduced on every forecast response:

> Weather data by Open-Meteo.com (CC BY 4.0). River discharge from GloFAS /
> Copernicus Emergency Management Service, served via Open-Meteo.

Open-Meteo is free for **non-commercial** use, which is what this student
research project is. See <https://open-meteo.com/en/terms>.

## Getting the data

```
.venv\Scripts\python scripts\data\fetch_flood_history.py --limit 10      # validate
.venv\Scripts\python scripts\data\fetch_flood_history.py --start 2019-01-01 --sleep 16
```

One Parquet file per district at `data/flood_history/<district_code>.parquet`
(`date`, `river_discharge_m3s`, `precipitation_mm`, `temperature_max_c`),
plus a `_manifest.json` recording what was fetched. The script is resumable:
a district whose file already reaches the requested end date is skipped.

### Why the window starts in 2019 and not 1984

**Quota, not data availability** — and this is worth stating plainly because
it is a real limitation of the result, not a design preference.

The script's default `--start` is `1984-01-01` (ask for everything; let the
provider decide what it has). GloFAS on Open-Meteo actually begins returning
values for Pakistani reaches around **1997**, which a first run confirmed:
10,853 days per district, no gaps.

That full pull is not affordable on the free tier. Open-Meteo's fair-use
limits are counted in **weighted** calls — roughly
`variables × days / 336` per request — so one 30-year daily pull is worth
far more than "one call". Measured against the free tier's ~10,000/day,
5,000/hour and 600/minute:

| Window | Days/district | Approx. total for 107 districts | Verdict |
|---|---:|---:|---|
| 1997–2026 | 10,853 | ~10,400 units | exceeds the **daily** budget |
| 2010–2026 | 6,100 | ~5,800 units | exceeds one **hourly** budget |
| 2019–2026 | 2,818 | ~2,700 units | fits |

This was not theoretical: a first attempt at the full history started
returning HTTP 429 at district 24, and the archive API's hourly budget was
exhausted outright. (The two endpoints have **separate** budgets — measured:
the archive API was refusing while the flood API still answered 200.) The
script now recognises an hourly-limit 429 by its response body and sleeps
until the hour rolls over rather than burning retries against a closed door.

So the shipped dataset covers **2019-01-01 onwards**. What that does and does
not buy:

- ✅ Includes the **2022** catastrophic floods in the training period.
- ✅ Gives a full, untouched calendar year (2023) for validation and 2.7
  years (2024 → Sep 2026), including three monsoon seasons, for test.
- ❌ Excludes the **2010** floods, and excludes the long baseline that would
  let the model learn genuinely rare behaviour. A model that has seen seven
  years cannot have learned what a 1-in-50-year event looks like.

Anyone with more quota, or willing to spread the download over several days,
can rerun with `--start 1997-01-01` and retrain; nothing else changes.

### The coordinate caveat, inherited and still true

District coordinates in `backend/ml/districts.py` are **approximate
city-centre placeholders**, so GloFAS attaches each query to its *nearest
modelled river reach*. For districts set back from the main channel that is
often a minor local stream rather than the Indus/Chenab/Kabul mainstem — the
measured median discharge at Multan's city centre is **0.03 m³/s**, which is
plainly not the Chenab.

This is the single biggest limitation of the whole feature, and it is
inherited from Flood Watch rather than introduced here (see
[FLOOD_RISK.md](FLOOD_RISK.md)). The numbers are real GloFAS output for the
reach they describe; they are just not always the reach a reader would
assume from the district name. Treat a forecast as an approximate,
city-level signal.

## The dataset

`backend/ml/flood_dl/dataset.py`, from `features.py`'s contract.

**Input window**: 14 consecutive days ending on the issue day `D0`, five
channels per day:

| # | Channel | Note |
|---|---|---|
| 0 | `log_discharge` | `log1p(m³/s)` |
| 1 | `precipitation_mm` | |
| 2 | `temperature_max_c` | |
| 3 | `day_of_year_sin` | seasonality as a circular pair, so 31 Dec and |
| 4 | `day_of_year_cos` | 1 Jan are adjacent rather than 357 days apart |

plus a **district id**, which indexes a learned embedding.

**Targets**: log discharge at `D0+1`, `D0+2`, `D0+3`.

**Why log discharge.** Pakistan's district reaches span about four orders of
magnitude. Trained on raw m³/s, one large river would dominate the loss and
the model would learn nothing about the other 106 districts. `log1p` also
handles the exact zeros a dry riverbed produces, which plain `log` does not.

**Windows never span a gap.** A window is built only where all 17 days are
consecutive calendar days with no missing value in any physical channel.
Stitching across a hole would teach the model a jump the river never made.

**Normalisation is per district**, mean/std of the three physical channels —
and computed on the **training rows only**. Using validation or test days
for normalisation is leakage, and it flatters every number below.

**The split is by time, never at random:**

| Split | Issue day `D0` |
|---|---|
| train | ≤ 2022-12-31 |
| val | in 2023 |
| test | ≥ 2024-01-01 |

A random split on a series this autocorrelated lets the model see Tuesday
and Thursday while being scored on Wednesday. It scores beautifully and
means nothing.

## The model

`backend/ml/flood_dl/model.py`.

```
window      (B, 14, 5)          district_id (B,)
                                      |
                                embedding(16)
                                      |
            concat -> (B, 14, 21)
                      GRU(hidden 64, 2 layers, batch_first)
                      take the final hidden state -> (B, 64)
                      Linear(64 -> 3)
            prediction (B, 3)   normalised log discharge at D+1, D+2, D+3
```

Small on purpose: the exported graph has to load inside the same 512 MB box
that already holds scikit-learn, SHAP and matplotlib (CLAUDE.md rule 11),
and a student project with this much autocorrelated data has no business
reaching for a model that could memorise it.

**Why a district embedding rather than 107 separate models**: each district
would see only ~1,400 training windows alone, and the districts that matter
most behave similarly enough that they should learn from each other. One
shared recurrent core learns *how a river rises*; the embedding gives each
district somewhere to put its own character.

## Training

```
.venv\Scripts\python -m pip install -r backend\requirements-ml.txt
.venv\Scripts\python backend\ml\flood_dl\train.py --register
```

Adam, Huber loss (`delta=1.0`) on normalised log discharge — river series are
spiky, and one monsoon peak should inform the model without dominating an
epoch's gradient. Early stopping on validation loss, and the **best**
validation weights are what get exported, not the last ones. Seeds are fixed
(`random`, `numpy`, `torch`), so a rerun reproduces the numbers.

<!-- METRICS:BEGIN -->

### The trained model

Registered version **`v20260925T164424165573Z`** — every number below is measured on the
held-out test split and reproduced verbatim from that version's
`metrics.json` by `scripts/write_flood_dl_metrics_doc.py`.

| | |
|---|---|
| Districts | 106 |
| Parameters | 43,555 |
| Total district-days | 298,708 |
| Date range | 2019-01-01 → 2026-09-18 |
| Training / validation / test windows | 153,488 / 38,690 / 104,834 |
| Epochs run (best) | 17 (13) |
| Training time | 394.9 s |
| Seed | 20260924 |
| Exported ONNX | 179,239 bytes, opset 14 |
| Max abs. difference ONNX vs PyTorch | 8.34e-07 |

### Accuracy vs the persistence baseline

Persistence is *"the river tomorrow is the river today"*. On a daily
discharge series that is a genuinely strong baseline, especially at D+1.

**log1p space** (scale-free — what the model optimises, and the fair
comparison across districts spanning four orders of magnitude):

| Horizon | Model MAE | Persistence MAE | Model RMSE | Persistence RMSE | Beats persistence |
|---|---:|---:|---:|---:|:---:|
| D+1 | 0.0341 (-0.0%) | **0.0341** | **0.1108** | 0.1258 | **no** |
| D+2 | **0.0523** (+8.1%) | 0.0569 | **0.1622** | 0.1854 | yes |
| D+3 | **0.0645** (+8.9%) | 0.0708 | **0.1853** | 0.2120 | yes |

**m³/s** (physical units — dominated by the largest rivers, which is
what a hydrologist reads), with Nash-Sutcliffe efficiency:

| Horizon | Model MAE | Persistence MAE | Model NSE | Persistence NSE |
|---|---:|---:|---:|---:|
| D+1 | 6.724 | **5.872** | 0.9937 | **0.9953** |
| D+2 | **10.129** | 11.071 | **0.9856** | 0.9835 |
| D+3 | **14.087** | 15.525 | **0.9733** | 0.9679 |

### The number that actually matters: lead time on real events

MAE is not what an early-warning system is for. This is: **of the days
that really were level ≥ 3 flood days, how many did the model flag at
least 24 hours ahead — and how often did it cry wolf?**

Measured over **104,834** test issue-days, of which
**2,433** were real level-≥3 days:

| | Model | Persistence |
|---|---:|---:|
| **Hit rate** (flagged ≥24 h early) | 0.5651 | 0.4583 |
| False-alarm ratio (FP / flagged) | 0.0846 | 0.0622 |
| False-alarm rate (FP / calm days) | 0.0012 | 0.0007 |
| True positives | 1375 | 1115 |
| False positives | 127 | 74 |
| False negatives | 1058 | 1318 |
| True negatives | 102274 | 102327 |

> An 'event day' is a test issue day D0 whose Flood Risk Index, computed from the discharge that actually occurred at D0+1..D0+3, maps to alert level >= 3 (band HIGH). A 'hit' is the same index computed from the model's prediction, issued at D0, reaching level >= 3 as well - i.e. at least 24 h of lead time. Rainfall, exposure, month and the 30-day baseline are held identical across model, persistence and actual, so only the discharge forecast differs.
>
> Observed rainfall over D0+1..D0+3 is used for all three series alike (a perfect rain forecast). This isolates the discharge model's lead-time skill; it is NOT an end-to-end operational score.

<!-- METRICS:END -->

## How it is served

`backend/app/services/flood_forecast.py`. **The API never imports PyTorch.**

torch is a ~200 MB dependency that exists in this project only to *train*
this model; it is pinned in `backend/requirements-ml.txt` alone, never in
`requirements.txt` and never in `requirements-deploy.txt`. The API loads the
exported **ONNX** graph (~170 KB) with **onnxruntime**, and even that import
is deferred until the first forecast is actually served.

Measured cost of the feature in a real process (`psutil` RSS, same method as
[MEMORY.md](MEMORY.md)):

| Step | RSS | Δ |
|---|---:|---:|
| interpreter + numpy (already paid by the API) | 29.5 MB | — |
| `import onnxruntime` | 49.7 MB | +20.2 MB |
| build the `InferenceSession` | 55.9 MB | +6.2 MB |
| 50 forecasts | 56.2 MB | +0.3 MB |
| **total, feature enabled** | | **+26.8 MB** |

With `FLOOD_DL_ENABLED=false` — the default — **none** of that is paid: the
import never happens. Against the 196 MB of headroom Phase 1 measured, 26.8 MB
is affordable, which is why `onnxruntime` is in the deployed image and torch
is not.

The exported graph is **verified before it is registered**: `export.py` runs
it through onnxruntime at four batch sizes and compares against the PyTorch
model, refusing to register a mismatch above `1e-4`.

### The endpoint

```
GET /api/v1/flood/forecast/{district}
```

Returns the 14 observed days the model read, the discharge it predicts for
D+1/D+2/D+3, the mapped Flood Risk Index score/band/components, the alert
level, the model version, the attribution, the training-data note and the
disclaimer.

It answers **503 with a reason** — never a fabricated forecast — when the
feature is disabled, no model is registered, the district was not in the
training set, or an upstream reading the window needs is missing.

## The FLOOD_FORECAST alert

A new alert type alongside the observed `FLOOD` one, raised on a **predicted**
level ≥ 2. See [ALERT_LEVELS.md](ALERT_LEVELS.md).

It is deliberately its **own type**, not a flag on `FLOOD`: the two have
different evidence behind them, a farmer must be able to tell "the river is
high" from "the river is expected to rise", and keeping them separate means
a forecast alert can never dedupe against, supersede or resolve an observed
one. A district can hold both at once.

The level is computed by delegating to the observed rule's own
`evaluate_flood()` with the predicted discharge substituted in — same band
table, same rising-48 h test, same thresholds — and then **clamped**:

| Setting | Default | Meaning |
|---|---|---|
| `ALERT_FLOOD_FORECAST_MIN_LEVEL` | `2` | below this, nothing is raised |
| `ALERT_FLOOD_FORECAST_MAX_LEVEL` | `3` | a forecast never raises above this |

**Why the ceiling.** Levels 4 and 5 take over the farmer's entire screen and
say *evacuate now*. A ~44k-parameter research model predicting three days
ahead, trained on seven years of data attached to approximate river reaches,
is not evidence enough to say that on its own. The observed `FLOOD` rule
still escalates to 4 and 5 the moment real discharge justifies it. When the
clamp bites, the alert records both the raw mapped level and the clamped one
and says so in its own text, so nothing is hidden.

Every FLOOD_FORECAST message, in English and Urdu, leads with the fact that
it is a **forecast, not a measurement**, names the model version, and states
that the prediction may be wrong in either direction.

## Limitations

Read these before quoting any number from this page.

1. **Coordinates are city-centre approximations**, so some districts are
   attached to a minor stream rather than the river their name implies. This
   is the largest source of error and it is not fixable without real reach
   coordinates.
2. **Seven years of history**, bounded by API quota, not by choice. The model
   has not seen a genuinely rare event and should not be expected to predict
   one.
3. **The level-hit-rate is measured with a perfect rain forecast.** Observed
   rainfall over the horizon is fed to the Flood Risk Index for the model's
   series, the persistence series and the actual label alike (the GRU itself
   only ever sees the past 14 days). That isolates the *discharge* model's
   lead-time skill; a real operational system would also have to predict
   the rain, and would do worse.
4. **The "actual" label is itself a model.** GloFAS discharge is model output,
   not gauge readings, so this measures agreement with GloFAS — not with the
   river.
5. **`FLOOD_DL_ENABLED` defaults to false**, even though the trained version
   is committed under `backend/ml/flood_dl/model/` (like the RandomForest's
   versions, it is ~200 KB). That is deliberate: the feature must be
   switched on knowingly.
6. **It is a research indicator.** NDMA/PMD/PDMA are authoritative.
7. **106 districts, not 107.** GloFAS on Open-Meteo returns no river
   discharge at all at **Gwadar**'s coordinate (recorded as `"status":
   "empty"` in `data/flood_history/_manifest.json`). Nothing was invented to
   fill the hole: the model has no embedding for Gwadar, and the forecast
   endpoint answers 503 ("was not part of the training set") for it rather
   than a forecast. Flood Watch's observed view is unaffected.
8. **At D+1 the model does not beat persistence.** Its log-space MAE is
   0.04 % *worse* (a tie in practice) and its m³/s MAE and NSE are worse
   too. The lead-time value is at D+2/D+3 (~8–9 % lower log MAE) and in the
   hit rate; a D+1 number from this model is no better than "tomorrow looks
   like today".

## Reproducing all of it

```
.venv\Scripts\python -m pip install -r backend\requirements-ml.txt
.venv\Scripts\python scripts\data\fetch_flood_history.py --start 2019-01-01 --sleep 16
.venv\Scripts\python backend\ml\flood_dl\train.py --register
.venv\Scripts\python -m pytest backend\tests -q
```

The test suite itself needs **none** of that: no torch, no network, no
trained model. The flood-forecast tests run against a committed
three-district ONNX fixture in `backend/tests/fixtures/flood_dl/`, regenerated
by `scripts/make_flood_dl_test_fixture.py`, whose `metrics.json` labels it as
an untrained fixture so its meaningless outputs can never be mistaken for
results.
