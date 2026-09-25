# User Guide — a short walkthrough of LEHAR

This is a quick tour for anyone opening the app for the first time — no
technical background needed. Once the app is running (see
`RUN-ME-FIRST.txt`), open **http://localhost:8000** and work through the
pages in this order for the fullest picture of what the platform does.

You don't need an account to look around — most pages work immediately for
anyone. Creating a free account (top-right "Log in" button → "Register")
additionally lets the app remember your saved fields and prediction history
between visits.

## 1. Dashboard

The home page. Pick a district from the dropdown at the top and you'll see
its current live weather, the day's irrigation recommendation on a simple
gauge, a 7-day forecast chart, and your recent predictions (once you've run
a few). If any district is under an elevated flood watch that day, a red
alert card appears here too — otherwise it stays hidden. This page is the
"at a glance" summary; everything on it links deeper into the page that
explains it.

## 2. Predict

The core tool: pick a district and crop, set the field's soil moisture and
canal water flow, and get an irrigation recommendation in millimetres.
Weather can be pulled live for the district or typed in by hand (useful if
you want to test a "what if" scenario, or if you're offline — manual mode
never needs an internet connection). Log in first if you want a prediction
saved to your history.

### Live soil moisture (optional)

Next to "Use live weather" there's a **Use live soil moisture** switch. It's
off by default, so the slider is whatever you set. Turn it on and the slider
fills in and greys out with an estimate for your district, labelled
*"model-estimated — Open-Meteo, not a field sensor"*. That's exactly what it
is: a weather model's guess for the area around the district's main city. It
can't know about your own field or whether you watered it yesterday, so if
you have a real reading, leave the switch off and use the slider. If the
estimate can't be fetched, the switch turns itself off, your own value comes
back, and a short note tells you why. You can always still get a
recommendation. The results panel shows which value was used and where it came
from. Full details: `docs/SOIL_MOISTURE.md`.

## 3. Explainability

Answers "why did the model say that?". Shows which of the model's 11 input
factors pushed the recommendation up or down for your last prediction (a
technique called SHAP), a plain-English summary sentence, and a confidence
range. There's also a model card lower on the page with the model's real,
measured accuracy — never an invented number.

## 4. Map

A map of all 107 supported districts, colored by irrigation demand. Click
any district for its live weather and recommendation. Switch the toggle at
the top to **Flood Watch** mode to instead see river-flood risk, sourced
from a real public river-discharge dataset (GloFAS) combined with recent
rainfall — districts are ranked LOW / WATCH / HIGH, with a "Top 10 at-risk"
list alongside the map.

## 5. Forecast

A 7-day weather outlook for one district — temperature, rainfall, and
humidity — plus an optional estimated irrigation demand line for each of
those 7 days, so you can plan ahead rather than one day at a time.

## 6. Compare

Put 2 to 6 districts side by side under the same crop and field conditions,
to see how weather and recommended irrigation differ across regions on the
same day.

## 7. Water Savings

A simple calculator: enter your field's current watering amount and the
app's recommended amount, and it converts the difference into estimated
litres saved for your field size (acres, hectares, or kanals). Pure
arithmetic, shown on the page — no hidden formula.

## 8. Reports

Download a branded Excel or PDF report of your prediction history and
irrigation summary — useful for sharing or record-keeping outside the app.

## 9. Models / Monitoring

For the curious: **Models** lists every trained version of the machine
learning model with its real accuracy metrics, and which one is currently
live. **Monitoring** shows real operational metrics (request counts,
response times) and a data-drift check that watches whether real-world
usage still looks like the data the model was trained on.

## AI assistant setup

The chat assistant (bottom-right button) is optional — every other page
works normally without it. To turn it on:

1. Get a free key at [console.groq.com](https://console.groq.com) →
   "API Keys" → "Create API Key".
2. Paste it when `START.bat` / `STARTUP-NO-DOCKER.bat` asks for it the
   first time you run the app (it's never echoed back on screen as you
   type), or add it later yourself to `backend\.env`'s `LLM_CLOUD_API_KEY=`
   line. `backend\.env` is the only file you need: it works whether the app
   runs with Docker or without. If you edit it while the app is running,
   double-click `STOP.bat` and then `START.bat` so the change is picked up.
   (The `.env` file next to `START.bat` only holds database and monitoring
   passwords — a key put there is ignored.)
3. Alternative, fully offline: install [Ollama](https://ollama.com), then
   run `ollama pull llama3.2:3b` in a terminal.

Without either, the assistant panel shows a friendly "not configured"
message instead of hanging — nothing else in the app is affected.

---

## Two honest notes

- **All data in this app is synthetic.** Every district's weather-response
  pattern, the training dataset, and the demo numbers you'll see were
  generated for research/demonstration purposes — not real agricultural
  records. Live weather and flood readings ARE real (pulled from public
  APIs), but the model that turns them into a recommendation was trained on
  synthetic data. This is stated in the app's footer on every page.
- **Flood Watch is a research indicator, not an official warning.** It's a
  transparent, documented formula (see `docs/FLOOD_RISK.md`) combining
  public river-discharge and rainfall data — useful for exploring the idea
  of a flood early-warning feature, but it is not validated against real
  flood outcomes and must never be used as a substitute for official
  government flood warnings.
