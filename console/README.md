# LEHAR Early-Warning Console

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> LEHAR is a research project, not an official warning service.

The public face of LEHAR: a mobile-first Next.js app in the style of a
national disaster-alert app (Japan's J-Alert / Safety Tips). The **alert is
the hero**. Open it and you see where, what level, and what to do.

It is a pure client of the LEHAR FastAPI backend in `../backend`. It has no
database or server logic of its own, and it never makes up data: every
number and every alert text comes from the API. Every failure is shown as an
honest error or empty state.

| Route | What it shows | API |
|---|---|---|
| `/` | National banner (highest level, one-line action), districts under an alert sorted by level, all-clear notices from the last 48 h, a level legend. **Level 4/5 opens a full-screen takeover.** | `GET /alerts/health-summary`, `/alerts/active`, `/alerts?type=ALL_CLEAR`, `/alerts/levels` |
| `/map` | Choropleth of the districts by current level. Click a district (or use the dropdown) to see actions, 7 days of observed river discharge + the DL forecast for D+1..D+3, and the latest alerts. | `/alerts/active`, `/flood/forecast/{d}` (falls back to `/flood/district/{d}` on 503), `/alerts?district=` |
| `/alerts` | Filterable feed (district, level, type, status), paged 50 at a time | `GET /alerts` |
| `/alerts/[id]` | One alert: bilingual text, timestamps, dedupe key and the full rule payload (the evidence) | `GET /alerts` (see backend gaps) |
| `/subscribe` | Telegram deep link + instructions, and email double opt-in (districts, min level 2–5, language) | `GET /alerts/telegram/link`, `POST /alerts/email/subscribe` |
| `/predict` | Irrigation recommendation form, result, top-5 SHAP reasons | `POST /predict`, `GET /meta` |
| `/explain` | Global feature importance (mean \|SHAP\|) | `GET /explain/global` |
| `/admin` | Login, then alert stats, the production model and data drift | `POST /auth/login`, `GET /alerts/stats` (JWT), `/models`, `/monitoring/drift` |

Every page has a header with an **EN / اردو** toggle (Urdu switches the whole
layout to right-to-left) and a footer that shows the disclaimer in both
languages (CLAUDE.md rule 12).

## Design rules this app holds itself to

- **Never colour alone.** A level is always shown as icon + level number +
  name. The colour tokens in `src/app/globals.css` mirror
  `backend/app/services/alerts/levels.py` (L1 white, L2 yellow, L3 red, L4
  purple, L5 black, OPS grey). `src/lib/__tests__/levels.test.ts` reads
  `levels.py` and fails if the two drift apart, or if any pair drops below
  WCAG AA contrast (4.5:1).
- **Level names and actions come from the API** (`GET /alerts/levels`), not
  from this repo. Until that answers, badges still show icon + number.
- **Alert text is never generated or translated here.** Titles, bodies and
  actions arrive from the backend in English and Urdu (CLAUDE.md rule 10).
  `src/i18n/dictionary.ts` only holds UI labels.
- **The takeover's "Acknowledge" is per device.** `POST /alerts/{id}/ack`
  changes the alert for *everyone*: it drops the alert from `/alerts/active`
  and from the national banner. A member of the public dismissing their own
  screen must not clear the warning for the rest of the country. So the
  console stores the acknowledgement in `localStorage`. The global ack is
  offered only to a logged-in admin, on the alert's detail page.
- **The alarm sound is off by default** and only plays after the user turns
  it on (a Web Audio tone, no audio file).
- **OPS notices (level 0) are admin only.** The public feed hides them and
  says so.
- **Synthetic data is labelled** on `/predict`, `/explain` and `/admin`
  (CLAUDE.md rule 13).

## "Server is waking up"

The backend runs on Render's free tier, which sleeps after ~15 minutes idle
and takes ~30–60 s to boot. `src/lib/api.ts` handles this. On a network error
or a bare 502/503/504 it retries with backoff (1, 2, 4, 8, then every 10 s)
for up to 60 s. While it retries, a banner reads "Server is waking up (free
tier), ~30-60 s" in English or Urdu.

LEHAR itself also answers 503 on purpose, for example when the flood
forecast is disabled or email is not configured. Those replies carry
LEHAR's JSON error body, so they are **not** retried. The page shows the
reason instead.

## Run locally

Prerequisites: Node 24 and npm 11, plus the LEHAR backend running on
port 8000 (see the root README, `START.bat`).

```bash
cd console
cp .env.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm ci
npm run dev                       # http://localhost:3000
```

The backend must allow the console's origin. `FRONTEND_ORIGINS` in
`backend/.env` already defaults to
`http://localhost:3000,http://127.0.0.1:3000`. If you changed it, add the
origin back, or the browser will block every request (CORS).

Quality gates (all run in CI, job `console` in `.github/workflows/ci.yml`):

```bash
npm run lint          # ESLint (next/core-web-vitals + typescript)
npx tsc --noEmit      # types
npm test              # vitest: level mapping, i18n completeness, API retry, flood series
npm run build         # production build
```

`NEXT_PUBLIC_API_URL` is inlined into the browser bundle **at build time**.
After changing it, rebuild. Restarting `next start` is not enough.

## Deploy on Vercel (free Hobby plan)

1. Import the GitHub repository in Vercel.
2. **Root Directory: `console`** (Project Settings → General). Vercel then
   detects Next.js and uses `npm ci` / `npm run build` by itself.
3. Environment Variables: `NEXT_PUBLIC_API_URL` =
   `https://<your-lehar-api>.onrender.com` (no trailing slash, no `/api/v1`),
   for Production and Preview.
4. Deploy. Then add the Vercel URL (e.g. `https://lehar-console.vercel.app`)
   to the backend's `FRONTEND_ORIGINS` on Render and redeploy the backend.
   Preview deployments get their own URLs; add any you want to test the same
   way.

No paid Vercel feature is used (CLAUDE.md rule 11).

## Screenshots

`../docs/screenshots/` is reserved for console screenshots. It is empty
for now and will be filled once the console runs against the deployed
backend (Phase 6).

## Project layout

```
console/
├── public/geo/pakistan_districts.geojson   # copied from frontend/assets/geo
├── src/app/                  # one folder per route (App Router)
├── src/components/           # header/footer, level badge, takeover, map, charts
├── src/i18n/                 # EN/UR dictionary + language provider (RTL)
└── src/lib/                  # api.ts (typed client), levels.ts, geo.ts, flood.ts
```

Six districts have no polygon in the vendored geoBoundaries file (Larkana,
Chiniot, Nankana Sahib, Sujawal, Mirpur, Kotli). The map page lists them
under the map, and they can still be picked from the dropdown.

## Known backend gaps (not fixed in Phase 5a, which changed no backend code)

1. **No `GET /alerts/{id}`.** The detail page pages through `GET /alerts`
   (500 per page, at most 10 pages) to find the id. That works, but it costs
   up to 10 queries for an old alert.
2. **Acknowledge is global and unauthenticated.** `POST /alerts/{id}/ack`
   has no auth, and it changes `/alerts/active` and `/alerts/health-summary`
   for every visitor. The console works around this with a per-device
   acknowledgement, but anyone can still call the endpoint directly.
3. **No server-side way to exclude OPS alerts** from `GET /alerts` (for
   example `?audience=farmer`). The console filters them in the browser, so
   the `count` it receives includes OPS rows it does not show.
4. **`GET /alerts` has no time filter** (for example `?since=`). All-clear
   notices are fetched as the 10 newest and trimmed to 48 h in the browser.
5. **No endpoint lists which districts have a flood forecast** (the DL
   model's training set). The map discovers it per district from a 503.
