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

## Design system — "LEHAR Command Center" (Phase 5b)

Dark-first, glass surfaces, the official level colours shown as glows. All
tokens live in `src/app/globals.css`; the level ones are mirrored in
`LEVEL_TOKENS` (`src/lib/levels.ts`) and **tested** (`levels.test.ts`).

| Layer | What it is |
|---|---|
| Page | Navy → charcoal gradient `#070B14 → #0E1524`, 1200 px content column (`.page`), 8-pt spacing |
| Surfaces | `.glass` / `.card`: 5 % white fill, 1 px 10 % white border, 16 px backdrop blur, `rounded-2xl`; `.lift` = 2 px / 150 ms hover lift |
| Type | `next/font` (downloaded at **build** time and self-hosted; the browser never calls Google): Sora (headings), Inter (body), JetBrains Mono (`.num`: numbers, timestamps), Noto Nastaliq Urdu (Urdu UI, taller leading). The hero numeral is `clamp(72px, 14vw, 160px)` |
| Level tokens | per level: `--lvl-N-bg/-fg` (official badge pair from `levels.py`), `--lvl-N-ink` (the level's colour for text, dots and rails on dark), `--lvl-N-glow`, `--lvl-N-gradient` + `--lvl-N-band-fg` (hero band). `.lvl-scope-N` sets the generic `--lvl-*` variables |
| Motion | framer-motion through `<LazyMotion strict>` (the feature bundle loads after first paint) + `<MotionConfig reducedMotion="user">`; the CSS animations stop under `prefers-reduced-motion` |

**Contrast is enforced by tests.** They fail if a level's badge pair, its
`ink` on any of the three dark surfaces (`#070B14`, `#0E1524`, glass
`#1C2331`), or its hero-band text on *either* gradient stop drops below
WCAG AA 4.5:1. L3's red band has the least margin (4.51:1), so the hero's
drifting mesh only ever *darkens* (`.band-mesh`).

How each level reads on the dark theme:

- **L1 calm**: deep teal band, white glow, green check. On the maps, calm districts get only a faint white wash, so the alerting ones stand out
- **L2 / L3 / L4**: official yellow / red / purple, used for the band gradient and for glowing rails, dots and map strokes
- **L5 black**: black band with a thin **pulsing white edge** (`.band-edge`) and a white ink, so it never disappears into the page
- **Never colour alone**: every level is still shown as icon + number + name (`LevelBadge`). Charts pair colour with line style (solid measured vs dashed forecast), arrows (SHAP up/down) or printed numbers

Motion:

- Route changes fade and rise over 250 ms. The first load paints without this, to protect LCP
- Switching EN ↔ UR flips the layout to RTL with a soft fade instead of a remount, so forms keep their input
- Lists reveal with a 40 ms stagger, and counters tick up (written straight to the DOM, so no re-renders)
- The hero gradient cross-fades when the national level changes, and pulse rings appear from Level 3
- The Level 4/5 takeover springs in
- The nav underline, tab indicator, language thumb and filter chips slide between options
- Skeletons shimmer while data loads

Layout: a sticky translucent header holds the wave wordmark, the nav and
the EN | اردو pill. Below 768 px the nav becomes a **bottom tab bar**
(Alerts now, Map, Alert feed, Subscribe, and More for Irrigation, Explain
and Admin). From 768 to 1023 px the top nav shows icons only, keeping the
labels for screen readers. From 768 px up, the EN + UR disclaimer strip is
pinned to the bottom of the viewport. On phones it ends every page instead:
pinned, a two-line strip plus the tab bar would cover a fifth of a small
screen.

Performance:

- The home mini-map is plain SVG from `public/geo/minimap.json` (50 KB, 18 KB gzip). `npm run minimap` pre-simplifies it from the 900 KB GeoJSON, and the page fetches it only once it scrolls into view
- Leaflet loads only on `/map`, and Recharts only in the map's district panel (lazily)
- `/explain` and `/predict` draw SHAP values as CSS glow bars, with no chart library
- On English pages the few Urdu lines use the device's Arabic-script font. The 240 KB Nastaliq file downloads only once a reader picks Urdu

Limits the design keeps to:

- The forecast chart shades the forecast *days*, not an uncertainty band. The API returns no band, and the console never invents one
- The subscribe step indicators never mark a step that happens outside the console (pressing Start in Telegram, clicking the email link) as done

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
npm test              # vitest: level mapping + dark-theme contrast, i18n completeness, API retry, flood series
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

`../docs/screenshots/` holds phone (360 px) and desktop (1280 px) captures
of `/`, `/map`, `/alerts` and `/subscribe`. They were taken against a local
backend and show real API data (on that day every district was calm at
Level 1). To retake them, use the optional Playwright script. Playwright is
not a dependency:

```bash
npm run build && npm start                  # console on :3000, backend on :8000
npm i --no-save playwright@1.63.0           # once; package.json stays untouched
npx playwright install chromium             # once, if no Chrome/Chromium is installed
npm run screenshots                         # writes ../docs/screenshots/*.png
```

Without Playwright, the script prints these steps and exits 0.

## Project layout

```
console/
├── public/geo/pakistan_districts.geojson   # copied from frontend/assets/geo
├── src/app/                  # one folder per route (App Router)
├── public/geo/minimap.json                 # simplified SVG paths (npm run minimap)
├── scripts/                  # build-minimap.mjs, screenshots.mjs (optional, Playwright)
├── src/components/           # chrome (header, tab bar, footer), Motion, LevelBand, level badge,
│                             # takeover, MiniMap, DistrictMap, charts, ShapBars, QrCode, Steps, Chips
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
