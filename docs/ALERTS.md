# LEHAR alert delivery — Telegram and email (Phase 3)

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> LEHAR is a research project, not an official warning service. Every
> message it sends says so.

The alert engine ([ALERT_LEVELS.md](ALERT_LEVELS.md)) decides *whether* an
alert fires, at *what* level and with *what* text — by fixed rules, never
by an LLM. This document is about the next step: getting that alert to a
farmer's phone. There are three channels:

| Channel | What it is | Needs |
|---|---|---|
| in-app | the alert row, shown by the console and the local frontend | nothing |
| Telegram | a bot message with an **Acknowledge** button | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `PUBLIC_BASE_URL` |
| email | a bilingual email sent through Brevo's HTTPS API | `BREVO_API_KEY`, `ALERT_FROM_EMAIL`, `PUBLIC_BASE_URL` |

**Every channel is optional.** With its variables left blank a channel
switches itself off: matching subscribers get a `skipped` delivery row that
names the missing variable, the in-app channel keeps working, and nothing
errors. LEHAR runs end-to-end offline with all of them blank.

Both providers are free: Telegram's Bot API has no cost, and Brevo's free
plan allows 300 emails a day. Email goes over **HTTPS**
(`api.brevo.com/v3/smtp/email`), never SMTP, because Render's free tier
blocks outbound SMTP ports.

---

## 1. Delivery rules

These are all implemented in `backend/app/services/alerts/channels/`
(`__init__.py` is the dispatcher).

- **Who gets an alert.** Every *verified* subscription whose channel the
  alert's level uses, whose district list contains the alert's district
  (an empty list means every district), and whose `min_level` is at or
  below the alert's level. Each subscriber gets the text in their own
  language (`en` or `ur`); emails carry both, theirs first.
- **Level 1 is never sent** to Telegram or email. It is the calm baseline
  and the per-field irrigation advisory, and stays in the app. A
  subscriber who sets `/level 1` still starts at level 2.
- **Levels 4 and 5 are re-sent every 6 hours** while the alert stays open
  (not resolved), labelled *Reminder*. Pressing **Acknowledge** in
  Telegram stops the reminders *for that chat only* — everyone else
  subscribed keeps getting them. A subscriber who joins while an
  emergency is open gets it on the next run.
- **Send budget.** One alert run makes at most `ALERT_MAX_SENDS_PER_RUN`
  (default 200) Telegram + email sends, re-sends included, spent **highest
  level first**. Sends past the cap are recorded as `skipped` with an
  error starting `Deferred:` and go out on the next run.
- **Retries.** A network error, timeout, HTTP 429 or 5xx is retried up to
  **3 times** with 1 s / 2 s / 4 s backoff (or the wait a 429 asks for, if
  ≤ 10 s). Any other 4xx — bad token, chat blocked the bot, unverified
  sender — is not retried. Timeouts are 5 s to connect, 10 s overall.
- **Failure isolation.** One channel failing never stops the other, and
  never fails the alert run. After 3 failed sends in a row within a run,
  a channel's remaining sends in that run are deferred to the next run
  instead of each waiting out its own retries.
- **Nothing is invented.** Every attempt writes an `alert_deliveries` row:
  `status` (`sent` / `failed` / `skipped`), `attempts`, `error`, and
  `latency_ms` — the time from the alert being raised (`created_at`) to
  the provider accepting the message. A reminder's latency is measured
  from the run that re-sent it.

### Prometheus

| Metric | Meaning |
|---|---|
| `lehar_deliveries_total{channel,status}` | every `alert_deliveries` row written |
| `lehar_delivery_latency_seconds{channel}` | raised → provider accepted, successful Telegram/email sends only |

---

## 2. Telegram

### 2.1 Create the bot (@BotFather)

1. In Telegram, open a chat with **@BotFather** (the blue-tick official one).
2. Send `/newbot`. Give it a display name (e.g. `LEHAR Alerts`) and a
   username ending in `bot` (e.g. `lehar_alerts_bot`).
3. BotFather replies with a **token** like `123456789:AAH...`. Treat it
   like a password. Put it in `backend/.env`:

   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   TELEGRAM_BOT_USERNAME=lehar_alerts_bot
   ```

4. Optional: `/setdescription` and `/setabouttext` — say it is a research
   advisory and that NDMA/PMD/PDMA warnings are authoritative.

### 2.2 Set the webhook

LEHAR uses **webhook mode only** (no polling process — a 512 MB host
cannot afford a second always-on loop). Telegram POSTs every update to
`<PUBLIC_BASE_URL>/api/v1/alerts/telegram/webhook`, and must present the
secret you choose here in the `X-Telegram-Bot-Api-Secret-Token` header —
the endpoint answers 401 without it, and 503 while it is unset.

```
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the output and your API's public HTTPS address in `backend/.env`:

```
TELEGRAM_WEBHOOK_SECRET=<the value printed above>
PUBLIC_BASE_URL=https://lehar-api.onrender.com
```

Then register it (also installs the `/` command menu):

```
.venv\Scripts\python scripts\set_telegram_webhook.py
.venv\Scripts\python scripts\set_telegram_webhook.py --info     # check it
```

On Render, set the same variables in the dashboard (they are declared in
`render.yaml` with `sync: false`) and run the script from your machine with
the same token, secret and URL in your local `backend/.env`.

### 2.3 Subscribing and the commands

A farmer subscribes by opening a **deep link**, which sends
`/start <district_code>` in one tap:

```
https://t.me/<TELEGRAM_BOT_USERNAME>?start=multan
https://t.me/<TELEGRAM_BOT_USERNAME>?start=dera_ghazi_khan
```

District codes are the district name, lower-case, spaces → `_` (see
`ml/districts.py`'s `district_code`). `GET /api/v1/alerts/telegram/link?district=Multan`
returns the link for any district, for the console to show.

| Command | Effect |
|---|---|
| `/start <district_code>` | subscribe this chat to that district (repeat to add more). A bare `/start` only shows help — it never subscribes to all 107 districts |
| `/stop` | stop all alerts (the row is kept, marked unverified, so history survives) |
| `/level <1-5>` | only alerts at this level or higher (default 2) |
| `/lang en` / `/lang ur` | message language |
| `/status` | the subscription, and each district's current level |
| **Acknowledge** button | marks the alert acknowledged (same as `POST /api/v1/alerts/{id}/ack`) and stops level 4/5 reminders for this chat |

Messaging the bot *is* the opt-in: Telegram only lets a bot write to a
chat that started a conversation with it, so Telegram subscriptions are
verified on `/start`.

---

## 3. Email (Brevo)

### 3.1 Get an API key and verify a sender

1. Create a free account at **brevo.com**.
2. **Verify a sender:** *Senders, Domains & IPs → Senders → Add a sender*,
   and confirm the email Brevo sends you. For better deliverability,
   also authenticate your domain (*Domains*) with the DNS records Brevo
   gives you. Brevo refuses to send from an unverified address.
3. **Create an API key:** *SMTP & API → API Keys → Generate a new API key*
   (a v3 key starting `xkeysib-`). Put it in `backend/.env`:

   ```
   BREVO_API_KEY=xkeysib-...
   ALERT_FROM_EMAIL=alerts@your-verified-domain.org
   ALERT_FROM_NAME="LEHAR Alerts"
   PUBLIC_BASE_URL=https://lehar-api.onrender.com
   ```

4. If Brevo answers `401` mentioning an unrecognised IP address, your
   account has *Authorised IPs* enforcement on (*Security → Authorised
   IPs*). Render's free tier has no fixed outbound IP, so turn the
   enforcement off for this key rather than allow-listing an address that
   will change.

### 3.2 Double opt-in

LEHAR never emails an address its owner did not confirm:

```
POST /api/v1/alerts/email/subscribe
{"email": "farmer@example.com", "districts": ["multan", "Sukkur"], "min_level": 3, "language": "ur"}
```

1. `subscribe` stores an **unverified** row and sends *only* a
   confirmation email (EN + UR) with a signed link that **expires after
   48 hours**. The requested districts/level/language travel inside that
   signed link and are applied only when it is clicked — so someone who
   types another person's address can neither subscribe them nor change
   their settings. The response is the same whether or not the address
   was already subscribed.
2. `GET /api/v1/alerts/email/verify?token=…` → verified; alerts start.
3. **Every alert email** carries an unsubscribe link
   (`GET /api/v1/alerts/email/unsubscribe?token=…`) and the RFC 8058
   `List-Unsubscribe` / `List-Unsubscribe-Post` headers, so mail clients
   show their own one-click Unsubscribe button (a `POST` to the same URL).

Links are JWTs signed with `JWT_SECRET` with their own `type` claim, so a
confirmation link can never be used as a login token, or vice versa.
`subscribe` shares the auth endpoints' per-IP rate limit.

---

## 4. Testing locally

**The automated tests need nothing** — no credentials, no network. Every
Telegram and Brevo call goes through a real `httpx.Client` over an
`httpx.MockTransport`, so they assert on the exact request LEHAR would send:

```
.venv\Scripts\python -m pytest backend\tests\test_alert_channel_telegram.py backend\tests\test_alert_channel_email.py backend\tests\test_alert_delivery_pipeline.py -q
```

`backend/tests/conftest.py` blanks every channel variable for the suite, so
a real token in your `backend/.env` can never message anyone from a test.

**Email, for real, on your own machine.** No tunnel is needed — only you
click the links, and your browser can reach `localhost`:

1. In `backend/.env`: `BREVO_API_KEY`, `ALERT_FROM_EMAIL`, and
   `PUBLIC_BASE_URL=http://localhost:8000`.
2. Start the API (`START.bat`, or the dev server command in CLAUDE.md).
3. Subscribe your own address:

   ```
   curl -X POST http://localhost:8000/api/v1/alerts/email/subscribe -H "Content-Type: application/json" -d "{\"email\": \"you@example.com\", \"districts\": [\"multan\"]}"
   ```

4. Click the link in the email → *Subscription confirmed*.

**Telegram, for real, on your own machine.** Telegram only delivers
webhooks to HTTPS, so expose the local API through a free tunnel, e.g.
`cloudflared tunnel --url http://localhost:8000` (prints an
`https://….trycloudflare.com` address), then:

```
.venv\Scripts\python scripts\set_telegram_webhook.py --url https://<your-tunnel-address>
```

Open `https://t.me/<your_bot>?start=multan` and try `/status`, `/level 3`,
`/lang ur`. When you are done, `--delete` removes the webhook (or re-run
the script against the deployed URL).

**Seeing a real alert go out.** Deliveries happen inside an alert run
(`POST /api/v1/alerts/run` with the `X-Alert-Run-Token` header —
[ALERT_LEVELS.md](ALERT_LEVELS.md)), and only for alerts the rules actually
raise from live data; LEHAR never fabricates an alert to test with. The
`alert_deliveries` table and `GET /api/v1/alerts/stats`'
`deliveries_by_status` show what was sent, skipped or failed, and why.

---

## 5. Subscription and operations API (Phase 4)

Every endpoint below is under `/api/v1/alerts`. Every JSON answer that
concerns an alert or a subscription carries `disclaimer` (and, where a
farmer reads it, `disclaimer_ur`) — *Research advisory — NDMA/PMD/PDMA
official warnings are authoritative*.

### Public (no account)

| Endpoint | Rate limit (per IP) | What it does |
|---|---|---|
| `POST /email/subscribe` | `RATE_LIMIT_AUTH_PER_MINUTE` (5) | Start the double opt-in. Body validated by `EmailSubscribeRequest`: `email`, `districts` (1–107 codes or names), `min_level` 2–5, `language` `en`/`ur`. **202** `{status: "verification_sent", message_en, message_ur, disclaimer, disclaimer_ur}` (`detail` = `message_en`, kept from Phase 3). 422 on bad input, 400 on an unknown district, 503 if email is not configured |
| `GET /email/verify?token=…` | `RATE_LIMIT_SUBSCRIPTION_PER_MINUTE` (20) | Apply the preferences in the signed link and mark the row verified |
| `GET` or `POST /email/unsubscribe?token=…` | same | Stop alerts (`verified=False`; delivery history kept) |
| `GET /telegram/link?district=…` | same | The one-tap `https://t.me/<bot>?start=<code>` link, plus `bot_username`, `start_command` and bilingual `instructions_en`/`instructions_ur`. 404 unknown district, 503 if `TELEGRAM_BOT_USERNAME` is unset. Subscribing itself happens when the person presses **Start** (the webhook verifies the chat); `/stop` unsubscribes |
| `GET /health-summary` | — (cached) | The console banner — see below |

**`?format=json` on verify and unsubscribe.** By default both return the
small bilingual HTML page a person sees after clicking a link in an email
(unchanged from Phase 3). With `format=json` they return the same outcome
as JSON, with the same status code:

```json
{"status": "verified", "message_en": "You will receive LEHAR research alerts for Multan at level 3 and above. …",
 "message_ur": "…", "districts": ["Multan"], "min_level": 3, "language": "ur",
 "disclaimer": "Research advisory — NDMA/PMD/PDMA official warnings are authoritative.", "disclaimer_ur": "…"}
```

`status` is `verified`, `unsubscribed` or `invalid_link` (HTTP 400 — bad,
expired, wrong-type or wrong-address token). The flow end to end:

```
POST /email/subscribe            -> 202 verification_sent   (row created, verified=false, one email sent)
GET  /email/verify?token=…       -> 200 verified            (verified=true, preferences applied)
GET  /email/unsubscribe?token=…  -> 200 unsubscribed        (verified=false)
```

### `GET /health-summary` — the public banner

```json
{"generated_at": "…", "highest_level": 3, "highest_level_key": "L3",
 "highest_level_name_en": "Warning", "highest_level_name_ur": "…",
 "highest_level_color_hex": "#E03131", "highest_level_text_color_hex": "…",
 "counts_by_level": {"1": 101, "2": 4, "3": 2, "4": 0, "5": 0},
 "total_districts": 107, "alerting_districts": 6,
 "cached": true, "cache_ttl_seconds": 60, "disclaimer": "…", "disclaimer_ur": "…"}
```

Built from exactly the rows `GET /active` serves, so the banner and the map
never disagree: a calm district counts at level 1, acknowledged/resolved
alerts, ALL_CLEARs and OPS notices never count. Cached for
`ALERT_HEALTH_SUMMARY_TTL_SECONDS` (60) with `Cache-Control: public,
max-age=60`; an alert run or an acknowledgement clears the cache at once, so
the TTL can only ever delay "nothing changed". It is still a database read —
point uptime pingers at `/api/v1/health` instead ([SCHEDULER.md](SCHEDULER.md)).

### Admin: `GET /stats` (JWT)

Phase 2's fields are unchanged; Phase 4 adds:

| Field | Meaning |
|---|---|
| `raised_by_type_and_level` | `{type: {level: n}}` over every alert row (a suppression writes no row, so every row was raised) |
| `resolved_by_type_and_level` | the same, for `status = resolved` |
| `suppressed_total` | all-time, the sum of every `alert_runs.alerts_suppressed` |
| `suppressed_by_type_and_level` + `suppressed_breakdown_scope` | per type/level, from the `lehar_alerts_suppressed_detail_total` counter. `alert_runs` only stores a per-run count, so this breakdown is **`since_process_start`** and resets when the API restarts (on Render free, whenever it spins down) — the response says so rather than passing it off as all-time |
| `deliveries_by_channel` | `{channel: {status: n}}` — `in_app` / `telegram` / `email` × `sent` / `failed` / `skipped` |
| `delivery_latency` | `{channel: {sample_size, median_ms, p95_ms}}` for Telegram and email, over the most recent ≤ 5000 successful sends per channel (bounded for the 512 MB host). Median is the textbook median; p95 is nearest-rank, so it is always a latency that actually happened. A channel with no sends is absent, never zero-filled |
| `active_subscriptions`, `active_subscriptions_by_channel` | verified subscriptions only — the ones that are actually messaged (`subscriptions` stays the raw row count) |
| `last_run.duration_seconds` | how long the most recent run took |

Scheduling the runs themselves, and running one by hand with
`scripts/run_alerts_once.py`, is covered in [SCHEDULER.md](SCHEDULER.md).
