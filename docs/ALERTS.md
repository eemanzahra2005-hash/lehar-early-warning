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
