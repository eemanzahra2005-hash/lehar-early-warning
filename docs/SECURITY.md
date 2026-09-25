# Security — hardening, audit, and honest limitations (Phase 11)

> Per CLAUDE.md rule 5, this is a local-first research/demo project — the
> goal of this phase is *solid fundamentals proportionate to that scope*,
> not enterprise-grade defense-in-depth. Every claim below was verified
> against this codebase, not assumed.

## JWT lifecycle: access + refresh tokens

Before this phase, a single JWT access token was valid for 7 days — a
stolen token stayed usable for a week. Phase 11 splits sessions into two
token types (`backend/app/auth.py`), each carrying a `type` claim so one
can never be replayed as the other even though both are signed with the
same `JWT_SECRET`:

| Token | Lifetime (env) | Purpose |
|---|---|---|
| Access | 60 min (`JWT_EXPIRE_MINUTES`) | Sent as `Authorization: Bearer <token>` on every authenticated request. |
| Refresh | 7 days (`JWT_REFRESH_EXPIRE_MINUTES`) | Exchanged for a new access token via `POST /api/v1/auth/refresh`. Never sent to any endpoint except `/refresh`. |

`register`/`login` return both tokens. `POST /api/v1/auth/refresh` takes a
refresh token and returns a new access token — it does **not** rotate the
refresh token itself (the client keeps using the same one until it expires
or the user logs in again); this was a deliberate scope decision, not an
oversight — refresh-token rotation adds real complexity (tracking used/
revoked tokens server-side) that isn't proportionate for a local-first demo
app with no server-side session store.

`frontend/js/api.js` handles token expiry transparently: on any `401`, it
tries **exactly one** silent `POST /auth/refresh` and retries the original
request once (`_isRetry` flag prevents a second attempt, so a request that
401s again right after a successful refresh — e.g. the refresh token itself
just expired — falls straight through instead of looping). Concurrent 401s
(e.g. several dashboard tiles fetching in parallel) share a single in-flight
refresh call instead of each firing their own. If the refresh itself fails,
the session is cleared and the login modal opens (`auth:unauthorized`
event) — the exact same clean failure path Phase 4 already had for a flat-
out invalid token.

**Not implemented, and out of scope for this phase:** refresh-token
revocation/blacklisting (would need a server-side token store — this app is
stateless JWT by design), and refresh-token rotation (see above).

## Password hashing (unchanged, verified)

Already met this phase's bar without changes — verified, not just assumed:

- PBKDF2-HMAC-SHA256, **600,000 iterations** (`backend/app/auth.py`,
  `PBKDF2_ITERATIONS`), a random 16-byte salt per user (`os.urandom(16)`).
- Verification uses `hmac.compare_digest()` — a constant-time comparison,
  not `==`, so password checking doesn't leak timing information about how
  many leading bytes matched.
- Plaintext passwords are never logged or stored — only the derived hash +
  salt hex strings.

## Rate limiting

Added via [slowapi](https://pypi.org/project/slowapi/) (`backend/app/rate_limit.py`)
— an in-memory, per-client-IP sliding-window limiter. In-memory (not
Redis-backed) is a deliberate fit for this single-process local-first app;
it would need a shared backend to work correctly across multiple worker
processes, which this project doesn't run.

| Route(s) | Limit (env) | Why |
|---|---|---|
| `POST /auth/register`, `/auth/login`, `/auth/refresh` | 5/min/IP (`RATE_LIMIT_AUTH_PER_MINUTE`) | Brute-force / credential-stuffing resistance. |
| `POST /predict` | 30/min/IP (`RATE_LIMIT_PREDICT_PER_MINUTE`) | Cheap per-call, but still bounds abuse/scraping of the ML endpoint. |
| `POST /assistant/chat` | 10/min/IP (`RATE_LIMIT_ASSISTANT_PER_MINUTE`) | Each call is a real LLM request — cloud API cost (Groq) or slow local CPU inference. |

A limit breach returns a clean `429` matching the app's existing uniform
error shape (`backend/app/middleware.py`'s `RateLimitExceeded` handler):

```json
{"error": "rate_limit_exceeded", "detail": "Too many requests — limit is 5 per 1 minute...", "status_code": 429}
```

Rate limiting is **disabled automatically for the entire pytest suite**
(most tests fire many requests in a loop and aren't testing this behavior)
**except one dedicated test** that re-enables it and asserts a real `429` —
see `backend/tests/conftest.py`'s `_disable_rate_limiting` fixture and
`backend/tests/test_rate_limit.py`. `slowapi.Limiter.enabled` is checked
live on every request (not baked in at decoration time), so flipping it at
runtime works with no app restart — verified by reading slowapi's own
source (`extension.py`) before relying on it.

## Secure response headers + Content-Security-Policy

`backend/app/middleware.py`'s `SecureHeadersMiddleware` adds these to
**every** response (API and static frontend alike):

- `X-Content-Type-Options: nosniff` — stops the browser from MIME-sniffing
  a response into executing as something other than its declared type.
- `X-Frame-Options: DENY` — this app is never meant to be framed by another
  site; blocks clickjacking.
- `Referrer-Policy: strict-origin-when-cross-origin` — full URL only on
  same-origin requests, origin-only cross-origin, nothing on a downgrade
  (https→http).
- `Content-Security-Policy`:

  ```
  default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  font-src 'self'; img-src 'self' data: https://tile.openstreetmap.org;
  connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'
  ```

  Built from what the app *actually* serves, not a generic template:
  - Every font (Inter, Space Grotesk, IBM Plex Mono) is vendored locally
    under `frontend/vendor/fonts/` (CLAUDE.md rule 7) — grepped `frontend/`
    for `fonts.googleapis.com`/`fonts.gstatic.com` before writing this
    policy: zero hits. So `font-src`/`style-src` stay same-origin; no
    Google Fonts *host* is needed even though the font *files* originated
    there.
  - The one genuine third-party origin is OpenStreetMap's raster tile
    server (`https://tile.openstreetmap.org` — Leaflet, `frontend/js/views/
    map.js`'s `tileLayer()` call uses this exact host, no `{s}` subdomain,
    so the CSP allow-lists exactly that, not a wildcard).
  - `style-src` needs `'unsafe-inline'` because Chart.js and Leaflet both
    set element `style` attributes directly from JS (canvas sizing, marker/
    tile positioning) — there is no way to avoid this without forking
    either vendored library.
  - `script-src 'self'` has **no** `'unsafe-inline'`/nonce exception:
    `frontend/index.html`'s pre-paint theme-flash-prevention snippet was
    externalized from an inline `<script>` block to `frontend/js/
    theme-init.js` specifically so this could stay strict.

  **Verified, not assumed:** a full Playwright sweep of every page (all 12
  routes, anonymous and logged-in, plus a real end-to-end register → login
  → run-a-prediction flow) with a `securitypolicyviolation` listener
  injected on every page found **zero** CSP violations and zero console
  errors; the Map page's OSM tiles were confirmed to actually decode and
  render (not just "no console error" — checked `naturalWidth > 0` on every
  tile `<img>` and that all tile network responses were HTTP 200).

## CORS

`CORS_ORIGINS` (`backend/app/config.py`) is a comma-separated allow-list,
currently defaulting to local dev origins only
(`http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500`).
**For any deployment beyond a single developer's machine**, tighten this to
the exact origin(s) the frontend is actually served from — e.g.:

```
CORS_ORIGINS="https://irrigation.example.com"
```

Never use `*` together with `allow_credentials=True` (which this app sets,
for the `Authorization` bearer header) — browsers reject that combination
outright, and even where they didn't, it would defeat the purpose of CORS
entirely.

## SQL injection

**Conclusion: no raw, string-interpolated SQL exists anywhere in this
codebase.** Verified by grepping the entire `backend/app/` tree for
`.execute(`, `exec_driver_sql`, and `text(` — the only three hits are all
in `backend/app/db.py`'s `_ensure_prediction_log_risk_columns()`
(`PRAGMA table_info(...)`, two `ALTER TABLE ... ADD COLUMN ...`
statements), and every one of them is a **fixed, hardcoded DDL string with
zero user input interpolated** — not an f-string, not `.format()`, not `%`
formatting. Every other database access in the app — all of `fields.py`,
`history.py`, `predict.py`, `auth.py`, and every service — goes through
SQLAlchemy's ORM query/filter API (`db.query(Model).filter(Model.x == value)`),
which parameterizes bound values automatically; there is no code path where
a request body, query param, or path param is concatenated into a SQL
string. `backend/migrations/` (Alembic) was checked the same way: clean.

## Secrets audit

- **`.env` was never committed, at either the `backend/.env` or root
  `.env` path, at any point in this repo's history** — verified with
  `git log --all --full-history -- backend/.env .env`, which returned
  empty (no commit ever touched either path).
- Searched the full history (`git grep` across every commit reachable from
  any ref) for `gsk_` (Groq API key prefix) and `JWT_SECRET=` outside
  `.env.example` files: the only `gsk_*` hits are the deliberately-fake
  `FAKE_CLOUD_KEY = "gsk_test_fake_key_should_never_leak_ABC123"` constant
  in `backend/tests/test_assistant.py` (used to assert a real key never
  leaks into a response body or log — see Phase 6.6), and there are zero
  `JWT_SECRET=` hits anywhere outside the two `.env.example` files (which
  intentionally contain only the placeholder
  `dev-only-change-me-in-your-.env`).
- Also swept history for AWS-style access key IDs (`AKIA[0-9A-Z]{16}`),
  PEM private-key headers (`-----BEGIN ... PRIVATE KEY-----`), and inline
  `password = "..."`-style literals outside test/doc files: zero hits.
- `.gitignore` covers every secret-bearing path this project produces:
  `.env` / `*.env` (with `!.env.example` explicitly re-allowed), `*.db` /
  `*.sqlite` / `*.sqlite3`, and `mlruns/` / `mlartifacts/` (MLflow's local
  tracking store, which can embed dataset paths and run metadata).
- `backend/.env.example` and the root `.env.example` were diffed
  programmatically against every field on `Settings`
  (`backend/app/config.py`) — every single env var the app reads has a
  documented entry with a safe placeholder. Nothing is missing.

**Generate a strong `JWT_SECRET`:**

```
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Paste the output into `backend/.env`'s `JWT_SECRET=`. Never reuse the
`dev-only-change-me-in-your-.env` placeholder outside throwaway local
testing — anyone who knows it can forge valid access *and* refresh tokens
for any username.

## Dependency audit (`pip-audit`)

Run with `.venv\Scripts\python -m pip_audit -r backend\requirements.txt`.
Two findings, both investigated rather than blindly bumped:

### `cryptography==49.0.0` — CVE-2026-69247 (PYSEC-2026-3552), fixed in 50.0.0

**Not upgraded — genuinely blocked, not neglected.** `mlflow==3.15.1` (the
latest available release; checked `pip index versions mlflow`) pins
`cryptography<50,>=43.0.0` — this was the exact reason `cryptography` was
already capped at 49.0.0 back in Phase 7 (see `backend/requirements.txt`'s
inline comment). Bumping to 50.0.0 would break `pip check` against mlflow
with no newer mlflow release available to relax the cap.

The vulnerable functions (`pkcs7_decrypt_der`/`_pem`/`_smime` — a
Bleichenbacher-style padding-oracle information leak in PKCS7/S-MIME
decryption) are **never called anywhere in this codebase** — this app has
no PKCS7 or S/MIME handling at all; `cryptography` is pulled in
transitively by `python-jose[cryptography]` (JWT signing, HS256 only — no
PKCS7 involved) and by mlflow itself. Real-world exploitability against
this app is therefore effectively nil despite the CVE being technically
present in the installed version. Revisit when mlflow relaxes its
`cryptography` ceiling in a future release.

### `ecdsa==0.19.2` — CVE-2024-23342 (PYSEC-2026-1325), **no fix available**

Minerva timing attack on P-256 ECDSA signing — the upstream
`python-ecdsa` maintainers have stated timing side-channels are out of
scope for a pure-Python implementation, so there is no patched version to
upgrade to (confirmed: `fix_versions: []` in the pip-audit result).

`ecdsa` is a transitive dependency of `python-jose` (`Required-by:
python-jose`, verified via `importlib.metadata`) — `python-jose` needs it
only to support the ES256/ES384/ES512 JWT algorithms. **This app never
uses those** — `backend/app/auth.py` signs and verifies exclusively with
`JWT_ALGORITHM = "HS256"` (HMAC, not ECDSA), so the vulnerable code path
(`ecdsa.SigningKey.sign_digest()`) is never invoked. Left as-is: the
package is installed but dead weight for this app's actual usage: swapping
JWT libraries solely to drop an unused transitive dependency wasn't judged
worth the risk of a working-code rewrite (CLAUDE.md rule 1) for a
finding that isn't reachable through this app's code paths.

## Docker image

`backend/Dockerfile` (new, Phase 11 — needed for CI and Phase 13's compose
wiring, not deployed anywhere yet):

- Multi-stage build: a `builder` stage installs pinned requirements into a
  venv, a slim `python:3.14-slim` runtime stage copies only that venv +
  application code — no compilers/build toolchain in the final image.
- Runs as a **non-root user** (`appuser`), not root.
- `backend/.dockerignore` keeps `.venv/`, `.env`, `.git/`, `mlruns/`,
  `__pycache__/`, and large optional CSVs out of the build context.
- `EXPOSE 8000`, entrypoint is `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Built locally and verified to succeed (`docker build`) — not wired into
  `docker-compose.yml` yet; that's Phase 13's job.

## What this phase deliberately did NOT do

Being explicit about scope, per this project's "proportionate, not
overengineered" instruction:

- No refresh-token rotation or server-side revocation list (see JWT
  section above) — would require a persistent token store this stateless-
  JWT app doesn't otherwise need.
- No Web Application Firewall, no DDoS protection beyond the per-IP rate
  limiter — out of scope for a local-first research app with no public
  deployment.
- No dependency auto-upgrade pipeline (e.g. Dependabot) — `pip-audit` is
  run manually per phase and as a non-blocking CI step (see
  `.github/workflows/ci.yml`); wiring up automated PRs is future work if
  this project ever needs continuous maintenance.
- CORS defaults still include local dev origins (`localhost:8000`,
  `localhost:5500`) — intentional for a project that has never been
  deployed anywhere beyond a developer's own machine; see the CORS section
  above for how to tighten this for a real deployment.
