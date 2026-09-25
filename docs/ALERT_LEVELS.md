# Alert levels

LEHAR issues **five farmer-facing alert levels** plus one **grey OPS level**
that only administrators ever see.

The five-level scheme is **inspired by Japan's five-level disaster alert
system** — the JMA / Cabinet Office "warning levels" (警戒レベル), where
level 1 is a white early advisory, 2 a yellow advisory, 3 a red warning,
4 a purple urgent warning, and 5 a black emergency. LEHAR borrows that
structure and its colours because the idea behind it is exactly what a
farmer needs: **the number itself is the instruction.** A farmer does not
have to interpret a discharge anomaly or a PSI value — they have to know
whether today is a "check the forecast" day or a "leave now" day.

What LEHAR does **not** borrow is Japan's thresholds. Those are calibrated
to Japanese river basins and Japanese rainfall. Every threshold in this
document is LEHAR's own, stated below with the reasoning behind it, and
every one is environment-configurable.

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> This sentence ends **every** message LEHAR produces, in every language, on
> every channel (CLAUDE.md rule 12). LEHAR is a research advisory system. It
> is never an official warning and must never present itself as one.

Alerts are **rule-based, deterministic and auditable — never LLM-generated**
(CLAUDE.md rule 10). Every level below comes from an explicit threshold
comparison in [`backend/app/services/alerts/rules.py`](../backend/app/services/alerts/rules.py),
and every message from a fixed string template in
[`templates.py`](../backend/app/services/alerts/templates.py). The same
inputs always produce the same alert, with the same words. An LLM may help a
farmer *read* an alert; it never decides whether one fires, what level it is,
or what it says.

The single source of truth for everything on this page is
[`backend/app/services/alerts/levels.py`](../backend/app/services/alerts/levels.py),
served live at `GET /api/v1/alerts/levels`.

---

## The levels at a glance

| # | Colour | Name (EN) | Name (UR) | Audience | Channels | Takeover |
|---|---|---|---|---|---|---|
| **0** | `#6B7280` grey | Operations Notice | آپریشنز اطلاع | admin only | in-app | no |
| **1** | `#FFFFFF` white | Early Advisory | ابتدائی اطلاع | farmer | in-app | no |
| **2** | `#FFD400` yellow | Advisory | انتباہ | farmer | in-app + Telegram + email | no |
| **3** | `#E03131` red | Warning | وارننگ | farmer | in-app + Telegram + email | no |
| **4** | `#7B2FBF` purple | Urgent Warning | فوری وارننگ | farmer | in-app + Telegram + email | **yes** |
| **5** | `#0B0B0B` black | Emergency | ہنگامی حالت | farmer | in-app + Telegram + email | **yes** |

"Takeover" means the Early-Warning Console and the local frontend interrupt
whatever the user is doing with a **full-screen takeover** rather than a
banner. Only levels 4 and 5 do this — if every level could take over the
screen, none of them would mean anything.

**OPS is number 0, not 6.** It sits *outside* the farmer urgency ladder
rather than above level 5, so a grey "the model drifted" notice can never
sort or render as worse than a black emergency.

---

## What is stored, and what is computed

This distinction matters more than any single threshold, so it comes first.

**Level 1 (white) is the calm baseline, and it is computed, not stored.**
`GET /api/v1/alerts/active` returns a row for **every** district: one whose
level comes from its highest active alert (`source: "alert"`), or — if it
has none — level 1 (`source: "default"`). Nothing is written to the database
for a calm district.

That is why a **LOW flood band raises no alert at all**. A calm river is the
normal state of almost every district on almost every day; writing 107 "the
river is fine" rows daily would bury the alerts that actually matter, in the
database and on the farmer's screen alike. An alert row means *something is
happening*.

Measured on a full 107-district sweep with every district in the LOW band
and calm weather: **0 alert rows stored, 107 districts returned at level 1.**
Two consecutive calm runs still store nothing, while both runs are recorded
in `alert_runs` — "the engine ran and found nothing" stays distinguishable
from "the engine never ran".

Only two things write level-1 rows:

- **IRRIGATION_DUE** — one per saved field per day. It is about a *specific
  field*, not a district-wide state, so it has something to say even on an
  otherwise calm day.
- **ALL_CLEAR** — it announces a past event and is born already resolved, so
  it never competes with the calm default.

A client tells the two apart with `source`: a real level-1 IRRIGATION_DUE
alert reports `source: "alert"` with a `type` and an `alert_id`; the calm
default reports `source: "default"` with all three null.

---

## Level 0 — OPS · Operations Notice (grey `#6B7280`)

**آپریشنز اطلاع** · admin only · in-app only · never shown to farmers

Platform health, not weather. Raised when the ML platform needs a human to
look at it.

**Actions (EN)**
- Admin only — no farmer action.
- Open the Monitoring page and review drift, the quality gate and the served
  model version.

**Actions (UR)**
- صرف منتظم کے لیے — کسان کے لیے کوئی کارروائی نہیں۔
- مانیٹرنگ صفحہ کھولیں اور ڈرفٹ، کوالٹی گیٹ اور زیرِ استعمال ماڈل ورژن کا جائزہ لیں۔

OPS alerts are filed under the district code `SYSTEM` and are excluded from
`GET /api/v1/alerts/active`, so they can never colour a district on a
farmer-facing map.

---

## Level 1 — Early Advisory (white `#FFFFFF`)

**ابتدائی اطلاع** · farmer · **in-app only** · no takeover

The normal state: nothing is happening here. No danger — plan normally.

Level 1 is the **calm baseline**, reported by `GET /api/v1/alerts/active`
for any district with no active alert, and computed rather than stored (see
[What is stored, and what is computed](#what-is-stored-and-what-is-computed)
above). The only level-1 alert rows are IRRIGATION_DUE and ALL_CLEAR.

Level 1 is deliberately in-app only: nothing at this level ever pushes a
message to someone's phone.

**Actions (EN)**
- Check today's forecast and your field's soil moisture.
- No protective action needed yet — plan your next irrigation normally.
- Keep watching LEHAR for updates.

**Actions (UR)**
- آج کی پیش گوئی اور اپنے کھیت کی نمی دیکھیں۔
- ابھی حفاظتی کارروائی ضروری نہیں — اگلی آبپاشی معمول کے مطابق کریں۔
- تازہ معلومات کے لیے لہر دیکھتے رہیں۔

---

## Level 2 — Advisory (yellow `#FFD400`)

**انتباہ** · farmer · in-app + Telegram + email · no takeover

Conditions are turning bad. Prepare the field and delay irrigation.

**Actions (EN)**
- Delay any planned irrigation until this advisory clears.
- Clear field drains and check tubewell and canal outlets.
- Move portable equipment and stored fertiliser to higher ground.

**Actions (UR)**
- یہ انتباہ ختم ہونے تک منصوبہ بند آبپاشی مؤخر کریں۔
- کھیت کی نالیاں صاف کریں اور ٹیوب ویل و نہری موگھے چیک کریں۔
- قابلِ منتقلی سامان اور ذخیرہ شدہ کھاد اونچی جگہ منتقل کریں۔

---

## Level 3 — Warning (red `#E03131`)

**وارننگ** · farmer · in-app + Telegram + email · no takeover

Damaging conditions are expected. Protect the crop, the livestock and the
household.

**Actions (EN)**
- Stop irrigation now and protect the crop that can still be saved.
- Move livestock, machinery and stored grain to higher ground.
- Keep documents, cash and medicines ready in one bag.

**Actions (UR)**
- آبپاشی فوراً بند کریں اور جو فصل بچ سکتی ہے اسے محفوظ کریں۔
- مویشی، مشینری اور ذخیرہ شدہ اناج اونچی جگہ منتقل کریں۔
- کاغذات، نقدی اور ادویات ایک بیگ میں تیار رکھیں۔

---

## Level 4 — Urgent Warning (purple `#7B2FBF`)

**فوری وارننگ** · farmer · in-app + Telegram + email · **full-screen takeover**

Move people and animals now. Do not wait for the water to arrive.

**Actions (EN)**
- Prepare to evacuate now — do not wait for water to reach the field.
- Move all livestock and everyone at home to the nearest safe high ground or
  shelter.
- Follow NDMA/PDMA instructions and local announcements.

**Actions (UR)**
- ابھی نقل مکانی کی تیاری کریں — پانی کے کھیت تک پہنچنے کا انتظار نہ کریں۔
- تمام مویشی اور گھر کے سب افراد کو قریبی محفوظ بلند جگہ یا پناہ گاہ منتقل کریں۔
- این ڈی ایم اے/پی ڈی ایم اے کی ہدایات اور مقامی اعلانات پر عمل کریں۔

---

## Level 5 — Emergency (black `#0B0B0B`)

**ہنگامی حالت** · farmer · in-app + Telegram + email · **full-screen takeover**

Life-threatening situation. Leave everything and get to safety.

**Actions (EN)**
- Evacuate immediately to the nearest safe high ground or relief camp.
- Leave crops, machinery and belongings behind — life first.
- Call 1122 or your local rescue service if you cannot move safely.

**Actions (UR)**
- فوراً قریبی محفوظ بلند جگہ یا ریلیف کیمپ کی طرف نقل مکانی کریں۔
- فصل، مشینری اور سامان چھوڑ دیں — پہلے جان بچائیں۔
- اگر محفوظ طریقے سے نہ نکل سکیں تو 1122 یا مقامی ریسکیو کو کال کریں۔

---

## What raises each level

Six rule families — the five below plus FLOOD_FORECAST, added in LEHAR
Phase 2.5. Every threshold is env-configurable; the values shown
are the **documented defaults** (`backend/.env.example`,
`app/config.py`, and `AlertThresholds` in `rules.py` all carry the same
numbers, and a test asserts they agree).

### FLOOD

Mapped directly from the existing Flood Risk Index band computed by
[`app/services/flood.py`](../backend/app/services/flood.py) (see
[FLOOD_RISK.md](FLOOD_RISK.md)), so the alert engine and Flood Watch can
never disagree about a district.

| Condition | Level |
|---|---|
| Flood Risk Index band `LOW` | **nothing raised** — the calm default |
| band `WATCH` (the index's middle band; `MEDIUM` accepted as a synonym) | **2** |
| band `HIGH` | **3** |
| band `HIGH` **and** river discharge rising ≥ 5% over the next 48 h | **4** |
| band `HIGH` **and** score ≥ 85 (the "extreme" sub-band), **or** a ≥ 20-year return period | **5** |

**A `LOW` band writes no alert row.** The district simply reports the
computed level-1 default on the active map. `LOW` is listed explicitly in
`FLOOD_CALM_BANDS` rather than merely being absent from the band map, so
this is visibly a decision and not an oversight — a test asserts both.

Levels 4 and 5 are reachable **only from within `HIGH`**. The Flood Risk
Index blends rainfall, exposure and seasonality into its score, so a large
discharge anomaly on its own can still land in `LOW` — and "evacuate now"
must never fire off a calm band.

**"Rising over the next 48 h"** compares the higher of the next two forecast
days' river discharge against today's, using the same GloFAS forecast slice
Flood Watch already fetches. A rise of at least
`ALERT_FLOOD_RISING_PCT` (5%) counts. A series shorter than three days
answers "not rising" rather than guessing.

**On the 20-year return period.** GloFAS via the free Open-Meteo Flood API
publishes river discharge only — **no return period**. Rather than fabricate
one (CLAUDE.md rule 4), LEHAR uses a documented **proxy**: the forecast peak
being at least `ALERT_FLOOD_RETURN_PERIOD_RATIO` (3.0×) the 30-day baseline
median. Every level-5 alert raised this way records
`"return_period_is_proxy": true` in its payload and says so in its text. If a
real return period ever becomes available on the discharge payload, the rule
uses that value directly and sets the flag to `false`. The proxy is a
rarity *heuristic*, not a computed return period, and is never described as
one.

### FLOOD_FORECAST

*Added in LEHAR Phase 2.5.* The same flood conditions as above, but
**predicted 1–3 days ahead** by the flood lead-time model
(`backend/ml/flood_dl/`, a small GRU trained on **real** GloFAS + ERA5
history) rather than read off today's GloFAS forecast — so an alert can fire
*before* the water arrives. Full methodology, the real measured metrics and
the limitations: [FLOOD_DL.md](FLOOD_DL.md).

| Condition | Level |
|---|---|
| predicted band `LOW` | **nothing raised** — the calm default |
| predicted band `WATCH` / `MEDIUM` | **2** |
| predicted band `HIGH` | **3** |
| raw mapping would give 4 or 5 | **clamped to 3** (see below) |

The level is computed by handing the model's predicted discharge to the very
same `evaluate_flood()` the observed rule uses — same band table, same
rising-48 h test, same thresholds — so a predicted level 3 means exactly
what an observed level 3 means, one day earlier. Today's observed discharge
is prepended to the predicted series so the rising test has something to
measure against.

**Its own type, deliberately.** FLOOD_FORECAST is not a flag on FLOOD. The
two carry different evidence, a farmer must be able to tell "the river *is*
high" from "the river is *expected* to rise", and separate types mean a
forecast alert can never dedupe against, supersede or resolve an observed
one. A district can legitimately hold both at once — for example an observed
`WATCH` (level 2) alongside a predicted `HIGH` (level 3).

**A forecast never reaches level 4 or 5.** `ALERT_FLOOD_FORECAST_MAX_LEVEL`
(default 3) clamps it one rung below the observed rule's ceiling. Levels 4
and 5 take over the farmer's entire screen and say *evacuate now*; a
~44k-parameter research model predicting three days ahead, trained on seven
years of history attached to approximate river reaches, is not evidence
enough to say that on its own — and the observed FLOOD rule still escalates
to 4 and 5 the moment real discharge justifies it. When the clamp bites, the
alert records **both** the raw mapped level and the clamped one, and says so
in its own text. Nothing is hidden; the ceiling is configuration, so it can
be raised later on the evidence in [FLOOD_DL.md](FLOOD_DL.md).

**Every message says FORECAST first**, in both languages, names the model
version, and states that the prediction may be wrong in either direction —
a flood it did not predict is still possible, and a predicted flood may not
arrive.

The rule is inert unless `FLOOD_DL_ENABLED=true` **and** a model is
registered under `backend/ml/flood_dl/model/`. Neither being true means the
rule simply does not run; every other rule is unaffected, and an alert run
on a checkout with no trained model behaves exactly as it did in Phase 2.

### HEAVY_RAIN

Open-Meteo daily `precipitation_sum` over the forecast window
(`ALERT_FORECAST_DAYS`, default 3). The **wettest single day** decides.

| Condition | Level |
|---|---|
| peak daily precipitation ≥ 30 mm | **2** |
| peak daily precipitation ≥ 80 mm | **3** |

A single day is the right unit: 80 mm spread over three days is a good
soaking; 80 mm in one day floods a field. The rule deliberately does **not**
fire on the three-day total.

### HEAT_STRESS

Open-Meteo daily `temperature_2m_max` over the same window.

| Condition | Level |
|---|---|
| ≥ 40 °C on **2 or more consecutive** days | **2** |
| ≥ 45 °C on any day | **3** |

Level 2 requires the heat to be **sustained** because a single 41 °C day is
an ordinary Pakistani summer day — it is multi-day heat that damages a crop.
Level 3 has no such requirement: 45 °C is damaging on its own, and any
45 °C day is by definition also a 40 °C day.

This rule reads `temperature_2m_max`, which is why LEHAR Phase 2 added
`WeatherService.fetch_daily_outlook()` rather than reusing
`fetch_forecast()` — that method returns `temperature_2m_mean`, and a
district can average 32 °C while peaking at 46 °C.

### IRRIGATION_DUE

The only rule that is about a **specific saved field** rather than a whole
district, the only decision-support (rather than danger) alert, and the only
rule that writes level-1 rows — so it is always level 1, in-app only.

| Condition | Level |
|---|---|
| model-recommended irrigation ≥ the field's threshold **and** < 1 mm of rain forecast over the next 3 days | **1** |

The threshold is the field's own `irrigation_threshold_mm` (set when the
field is saved), falling back to `ALERT_IRRIGATION_THRESHOLD_MM` (10 mm)
for a field that has none — which includes every field saved before this
phase.

If the model cannot produce a number, **no alert fires** — never an invented
one (CLAUDE.md rule 4).

**One alert per saved field per day.** Two fields on the same farm are two
separate irrigation decisions, so each gets its own alert, its own dedupe
key and its own life cycle — one field going quiet never resolves the
other's advisory. The rule carries a `subject` of `field:<id>` which the
engine folds into the dedupe key (see below).

### OPS

Platform health. Raised at level 0 under the district code `SYSTEM`.

| Condition | Source |
|---|---|
| worst per-feature PSI ≥ `DRIFT_PSI_ALERT` (0.25) | [`app/services/drift.py`](../backend/app/services/drift.py), computed live during the run |
| a training run **failed the quality gate** | `backend/ml/pipeline.py` |
| the served model was **rolled back** | `POST /api/v1/models/rollback` |

The PSI trigger deliberately has no threshold of its own — it reuses
`DRIFT_PSI_ALERT` so an OPS alert and `GET /api/v1/monitoring/drift` can
never disagree about what "alert" means. When drift reports
`insufficient_data`, no PSI is available and the trigger stays silent: no
data is not the same as no drift.

The gate and rollback triggers arrive through
[`ops_events.py`](../backend/app/services/alerts/ops_events.py), a small
append-only JSON-lines file. It is a file rather than a table because the
training pipeline runs in its own process with no API database session.
Events older than `ALERT_OPS_EVENT_MAX_AGE_HOURS` (24 h) are ignored, and
consuming them into an alert clears them — so one rollback raises one alert,
not one every run for a day.

---

## How an alert behaves over its life

### Dedupe

Every alert carries a **dedupe key**:

```
district + type + level + day        e.g.  Multan|FLOOD|3|2026-08-12
```

That key is `UNIQUE` **in the database**, not merely checked in code — so
even two concurrent runs cannot raise the same alert twice. An unchanged
condition re-evaluated an hour later is suppressed, not re-sent.

A rule whose outcome is about something narrower than a district widens the
type half of the key with its **subject**. Today that is only
IRRIGATION_DUE:

```
Multan|IRRIGATION_DUE:field:12|1|2026-08-12
Multan|IRRIGATION_DUE:field:13|1|2026-08-12    <- a different field, a different alert
Multan|ALL_CLEAR:FLOOD|1|2026-08-12            <- all-clears are keyed the same way
```

The subject is also stored in the alert payload, and the engine uses
`(district, type, subject)` as the identity for escalation, cooldown and
resolution — so a field's advisory has a life cycle entirely of its own.

### Cooldown

`ALERT_COOLDOWN_HOURS` (default **12 h**). An unchanged (or lower)
condition may re-notify at most this often, even across a day boundary
where the dedupe key would otherwise be fresh.

### Escalation

**Escalation to a higher level always creates a new alert and always ignores
the cooldown.** A farmer must never have to wait out a cooldown to be told
things got worse. The superseded lower-level alert is closed with
`resolution_reason: "superseded"`, so a district never shows two open alerts
of the same type, and the history of what the farmer was actually told
survives intact — levels are never edited in place.

De-escalation works the same way once the cooldown has elapsed: the higher
alert is closed and a new one is raised at the level that is true now.

### Acknowledgement

`POST /api/v1/alerts/{id}/ack` marks an alert *acknowledged* — "I have seen
this". It does **not** resolve it: the underlying condition is still there,
so the alert keeps being tracked and still resolves only when the condition
actually goes away. Acknowledging a resolved alert is a 409.

### Resolution and ALL_CLEAR

An active alert whose condition produces **no outcome for
`ALERT_CLEAR_RUNS_TO_RESOLVE` (default 2) consecutive runs** is resolved,
and an `ALL_CLEAR` alert is emitted for it.

Two runs, not one, because a single failed upstream fetch must never be able
to declare a flood over.

The `ALL_CLEAR` is **level 1** — good news must never blast at the urgency
of the warning it ends — and is born already resolved, since it announces a
past event rather than an ongoing condition. That is also why it never
shows up on the active map: the district goes back to the computed calm
default the moment its alert resolves.

---

## Channels

| Channel | Status |
|---|---|
| in-app | **working** (Phase 2) — the alert row itself, read via `GET /api/v1/alerts` |
| Telegram | **working** (Phase 3) — Bot API over HTTPS, webhook commands, Acknowledge button |
| email (Brevo) | **working** (Phase 3) — Brevo HTTPS API, double opt-in, unsubscribe link in every email |

Level 1 is **never** pushed to Telegram or email — it stays in the app.
Levels 4 and 5 are **re-sent every 6 hours** while the alert stays open, to
each subscriber who has not pressed Acknowledge. Setup, the bot commands
and the delivery rules are in [docs/ALERTS.md](ALERTS.md).

Every delivery attempt — including skips — is written to `alert_deliveries`,
so "why didn't I get this?" always has an answer in the data. A channel
whose credentials are not configured records an honest
`status: "skipped"` naming the missing variable, never a fabricated
`"sent"` (CLAUDE.md rule 4). An **unverified** subscription is never
messaged.

---

## Configuration

Every value below is an environment variable; see `backend/.env.example` for
the full annotated list.

| Variable | Default | Meaning |
|---|---|---|
| `ALERT_RUN_TOKEN` | *(empty)* | Shared secret for `POST /api/v1/alerts/run`. Empty = the endpoint refuses every call with 503. |
| `ALERT_COOLDOWN_HOURS` | `12.0` | Minimum gap before an unchanged condition re-notifies. |
| `ALERT_CLEAR_RUNS_TO_RESOLVE` | `2` | Consecutive clear runs before resolve + ALL_CLEAR. |
| `ALERT_FORECAST_DAYS` | `3` | Days of daily forecast pulled per district. |
| `ALERT_FLOOD_RISING_PCT` | `0.05` | 48 h discharge rise for level 4. |
| `ALERT_FLOOD_EXTREME_SCORE` | `85.0` | Flood Risk Index "extreme" sub-band for level 5. |
| `ALERT_FLOOD_RETURN_PERIOD_RATIO` | `3.0` | Proxy multiple of the 30-day baseline for a rare event. |
| `ALERT_FLOOD_RETURN_PERIOD_YEARS` | `20` | The return period that proxy stands in for. |
| `FLOOD_DL_ENABLED` | `false` | Master switch for the flood lead-time model (Phase 2.5). False = the FLOOD_FORECAST rule never runs. |
| `FLOOD_DL_MODEL_VERSION` | `latest` | Which registered flood lead-time model to serve. |
| `ALERT_FLOOD_FORECAST_MIN_LEVEL` | `2` | Quietest predicted level that raises a FLOOD_FORECAST alert. |
| `ALERT_FLOOD_FORECAST_MAX_LEVEL` | `3` | Ceiling for a predicted level — keeps a forecast out of the level-4/5 evacuate territory. |
| `ALERT_HEAVY_RAIN_L2_MM` | `30.0` | Peak daily rainfall for level 2. |
| `ALERT_HEAVY_RAIN_L3_MM` | `80.0` | Peak daily rainfall for level 3. |
| `ALERT_HEAT_L2_C` | `40.0` | Daily max temperature for level 2. |
| `ALERT_HEAT_L3_C` | `45.0` | Daily max temperature for level 3. |
| `ALERT_HEAT_CONSECUTIVE_DAYS` | `2` | Consecutive hot days required at level 2. |
| `ALERT_IRRIGATION_THRESHOLD_MM` | `10.0` | Fallback per-field irrigation trigger. |
| `ALERT_IRRIGATION_DRY_MM` | `1.0` | Total rain below which the window counts as dry. |
| `ALERT_IRRIGATION_DRY_DAYS` | `3` | Length of that dry window. |
| `ALERT_OPS_EVENTS_PATH` | `backend/data/ops_events.jsonl` | Where gate/rollback breadcrumbs live. |
| `ALERT_OPS_EVENT_MAX_AGE_HOURS` | `24.0` | How long a breadcrumb stays eligible. |
| `DRIFT_PSI_ALERT` | `0.25` | Reused by the OPS rule — see [DRIFT.md](DRIFT.md). |

---

## A note on the data

LEHAR's irrigation model is trained on **SYNTHETIC research data**
(CLAUDE.md rules 4 and 13). Weather and river-discharge values are live
Open-Meteo / GloFAS readings, and district coordinates are approximate
city-centre placeholders — see [FLOOD_RISK.md](FLOOD_RISK.md) and
[SOIL_MOISTURE.md](SOIL_MOISTURE.md). Every farmer-facing alert message says
so in its own body, not only here.

And once more, because it is on every message LEHAR ever sends:

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
