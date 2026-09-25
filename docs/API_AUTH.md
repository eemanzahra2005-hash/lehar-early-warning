# API authentication

**Written for: developers building a client against the LEHAR API — in
particular the separate Next.js Early-Warning Console (LEHAR Phase 5), which
runs on a different origin from this backend.**

LEHAR's API uses **bearer tokens**: a JSON Web Token sent in the
`Authorization` header. There are no session cookies anywhere in this API,
which is what makes a split deployment (console on Vercel, API on Render)
straightforward — there is no cookie domain, `SameSite` or CSRF interaction
to reason about.

> **Research advisory — NDMA/PMD/PDMA official warnings are authoritative.**
> Every alert and flood response this API returns carries that disclaimer.
> LEHAR is a research advisory and never an official warning. All data served
> by this API is SYNTHETIC research data.

---

## The short version

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "username": "alice", "password": "…" }
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs…",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs…",
  "username": "alice"
}
```

Then send the access token on every subsequent request:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIs…
```

When the access token expires (60 minutes by default), exchange the refresh
token for a new one at `POST /api/v1/auth/refresh` rather than asking the
user to log in again.

---

## Endpoints

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/v1/auth/register` | `{username, password, email?}` | `201` + `{access_token, refresh_token, username}` |
| `POST /api/v1/auth/login` | `{username, password}` | `200` + `{access_token, refresh_token, username}` |
| `POST /api/v1/auth/refresh` | `{refresh_token}` | `200` + `{access_token, token_type, username}` |

`/register` and `/login` also return `token_type: "bearer"`, which is
informational — it is always `"bearer"`.

**`/refresh` does not rotate the refresh token.** Its response contains an
`access_token` but no `refresh_token`: the client keeps using the same
refresh token until it expires or the user logs in again. Merge the refresh
response into your stored tokens rather than replacing them, or you will
overwrite a perfectly good refresh token with `undefined`.

`/refresh` returns `401` (never `422`) on every failure — expired, malformed,
an access token presented in its place, or a since-deleted user — so a client
can handle all of them with one branch.

Failure modes worth handling explicitly:

- `409` from `/register` — the username is taken.
- `401` from `/login` — wrong username or password. The response does not
  distinguish the two, on purpose.
- `429` from any of the three — rate limited. Auth endpoints get the
  tightest per-IP limit in the API (`RATE_LIMIT_AUTH_PER_MINUTE`, default
  5/min) because they are the credential-stuffing surface. The response body
  explains the limit; back off rather than retrying immediately.

## Two token types

Both are HS256 JWTs signed with `JWT_SECRET`, carrying `sub` (the username)
and a `type` claim that is checked on every use — presenting a refresh token
where an access token is expected fails, and vice versa.

| | lifetime (default) | setting | used for |
|---|---|---|---|
| access token | 60 minutes | `JWT_EXPIRE_MINUTES` | every authenticated request |
| refresh token | 7 days | `JWT_REFRESH_EXPIRE_MINUTES` | obtaining a new access token |

The split is deliberate: a leaked access token is useful for an hour rather
than a week, while the user still stays signed in for a week.

## Which endpoints need a token

**Required** — `401` without a valid access token:

- `/api/v1/fields/*` — a user's saved fields
- `/api/v1/history/*` — a user's prediction history
- `/api/v1/report/*` — Excel/PDF report exports
- `/api/v1/models/{version}/promote`, `/api/v1/models/rollback` — changing
  which model version is served

**Optional** — works signed-in or anonymous, and behaves slightly differently:

- `POST /api/v1/predict` — anonymous predictions work fully; with a token,
  the prediction is attributed to the user and can reference a saved field.
- `/api/v1/assistant/*`

An invalid or expired token on an *optional-auth* endpoint is treated as
"anonymous", not as an error — the request still succeeds.

**Public** — no token, ever: `/api/v1/health`, `/api/v1/health/deep`,
`/api/v1/meta`, `/api/v1/weather/*`, `/api/v1/flood/*`, `/api/v1/map/*`,
`/api/v1/monitoring/*`, `/api/v1/models` (read-only listing), `/metrics`.

---

## Calling the API cross-origin

The console is **not** same-origin with this API, so the browser applies CORS.
Allowed origins come from two comma-separated environment variables that are
merged (de-duplicated, order preserved) by `app/config.py`:

| variable | meaning | default |
|---|---|---|
| `CORS_ORIGINS` | origins this repo's own vanilla frontend is served from | `http://localhost:8000,http://127.0.0.1:8000` |
| `FRONTEND_ORIGINS` | origins of separate frontends — the console | `http://localhost:3000,http://127.0.0.1:3000` |

They are kept separate so adding the console's origin can never silently stop
this repo's own frontend from working. **A console running on
`localhost:3000` against a local API needs no configuration at all** — that
origin is allowed by default.

For a deployed console, set `FRONTEND_ORIGINS` to its real origin:

```
FRONTEND_ORIGINS=https://lehar-console.vercel.app,http://localhost:3000
```

`render.yaml` sets exactly this for the `lehar-api` service. Origins must be
scheme + host + port with **no trailing slash** and no path — `https://x.app`,
never `https://x.app/`. An origin that does not match exactly is simply not
granted access.

Because `Authorization` is not a CORS-safelisted header, every authenticated
call is preflighted with `OPTIONS` first. That is handled automatically; the
only requirement is that the calling origin is listed above.

### Example client

```js
const API = process.env.NEXT_PUBLIC_LEHAR_API_URL; // https://lehar-api-xxxx.onrender.com

async function login(username, password) {
  const res = await fetch(`${API}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(`Login failed: ${res.status}`);
  return res.json(); // { access_token, refresh_token, username }
}

async function apiFetch(path, { accessToken, refreshToken, onTokens, ...init } = {}) {
  const call = (token) =>
    fetch(`${API}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

  let res = await call(accessToken);

  // One silent refresh on 401, then give up and let the caller sign in again.
  if (res.status === 401 && refreshToken) {
    const refreshed = await fetch(`${API}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (refreshed.ok) {
      // Note the spread: /refresh returns no refresh_token, so merge rather
      // than replace — otherwise the stored refresh token is lost.
      const tokens = { refreshToken, ...(await refreshed.json()) };
      onTokens?.(tokens);
      res = await call(tokens.access_token);
    }
  }
  return res;
}
```

Retry **once** on `401`. A second failure means the refresh token is expired
or revoked, and the user has to sign in again — retrying in a loop will only
hit the auth rate limit.

Do not send `credentials: "include"`. This API authenticates from the
`Authorization` header only; including credentials adds cookie semantics that
nothing here uses.

---

## Configuration and operational notes

| variable | purpose |
|---|---|
| `JWT_SECRET` | signs and verifies every token. **Must** be a long random value in any real deployment |
| `JWT_EXPIRE_MINUTES` | access-token lifetime (default 60) |
| `JWT_REFRESH_EXPIRE_MINUTES` | refresh-token lifetime (default 10080 = 7 days) |
| `CORS_ORIGINS` / `FRONTEND_ORIGINS` | allowed browser origins (above) |
| `RATE_LIMIT_AUTH_PER_MINUTE` | per-IP limit on the auth endpoints (default 5) |

Generate a real secret with:

```
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`render.yaml` declares `JWT_SECRET` as `sync: false`, so it is set in the
Render dashboard and never committed — see
[DEPLOY_RENDER.md](DEPLOY_RENDER.md).

**Rotating `JWT_SECRET` invalidates every issued token immediately**, access
and refresh alike. Every user has to sign in again. That is the intended
emergency response to a suspected leak; there is no per-token revocation
list.

Tokens are stateless and are not stored server-side, so there is no
server-side logout — a client logs out by discarding its tokens. Both tokens
are bearer credentials: store them where a hostile script on the page cannot
read them, and never log them or put them in a URL.

See [SECURITY.md](SECURITY.md) for the wider security posture (password
hashing, rate limiting, security headers).
