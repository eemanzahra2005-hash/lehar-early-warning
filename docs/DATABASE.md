# Database — SQLite default, PostgreSQL via Docker Compose (Phase 9)

> Per CLAUDE.md rule 5, everything below runs entirely on the local machine
> — the "production-style" database here means "the same engine a real
> deployment would use," not an actual hosted/cloud database.

## Overview

Every phase before this one used a single SQLite file
(`backend/data/app.db`) with zero setup. Phase 9 adds an **optional**
PostgreSQL path for anyone who wants to develop against something closer to
a production database — but SQLite stays the default, and nothing about the
zero-Docker workflow changes for anyone who doesn't opt in.

`backend/app/db.py` builds its SQLAlchemy engine from a single source of
truth, `resolve_database_url()`:

- `DATABASE_URL` env var set → used verbatim (Postgres, or any other
  SQLAlchemy URL).
- `DATABASE_URL` unset (the default) → `sqlite:///<DB_PATH>`, exactly the
  URL every phase before Phase 9 built.

SQLite-specific behavior (`check_same_thread=False` connect arg, creating
the parent folder) is applied conditionally, only when the resolved URL's
dialect is `sqlite`.

## SQLite mode (default, zero setup)

Nothing to configure. Run the app exactly as before:

```
.venv\Scripts\uvicorn app.main:app --reload --app-dir backend
```

On startup, `init_db()` runs `Base.metadata.create_all()` against the
SQLite file at `DB_PATH` (default `backend/data/app.db`), plus the existing
idempotent additive-column check for `prediction_logs.risk_score`/
`risk_band` (Phase 6). This is unchanged from every earlier phase.

The full test suite also runs on SQLite — each test session gets its own
temp SQLite file (`backend/tests/conftest.py`), so tests never need Docker
or a real Postgres server.

## PostgreSQL mode

### 1. Start the database

`docker-compose.yml`'s `db` service (`postgres:16-alpine`) reads its
credentials from a **root-level** `.env` (project root, not `backend/.env`
— compose only reads `${VAR}` substitutions from a `.env` next to the
compose file). Copy the placeholders and pick a real local password:

```
copy .env.example .env
```

Then start it:

```
docker compose up -d db
docker compose ps db          REM should show "healthy" (pg_isready healthcheck)
```

Data persists in the named volume `postgres_data` across restarts;
`docker compose down -v` removes it if you want a clean slate.

### 2. Point the app at it

Add one line to `backend/.env` (matching the credentials in your root
`.env`):

```
DATABASE_URL=postgresql+psycopg://irrigation:<your-password>@localhost:5432/smart_irrigation
```

**Driver note:** this project uses **psycopg v3** (`psycopg[binary]`), not
`psycopg2-binary` — `psycopg2-binary` has no prebuilt wheel for Python 3.14
on Windows yet and fails to build from source (needs `pg_config`). psycopg
v3's binary wheel installs cleanly, so the URL scheme is
`postgresql+psycopg://` (not the classic `postgresql://` /
`postgresql+psycopg2://`).

### 3. Apply migrations

Once `DATABASE_URL` points at Postgres, **Alembic migrations are the sole
source of truth for schema there** — `init_db()`'s `create_all()` fallback
is SQLite-only and is a deliberate no-op when the resolved URL isn't SQLite
(see `backend/app/db.py`). Run:

```
scripts\db_upgrade.bat
```

(`scripts/db_upgrade.sh` on macOS/Linux.) This runs `alembic upgrade head`
using whatever `DATABASE_URL` is currently set — either from `backend/.env`
or an exported shell variable, which takes priority for one-off runs
without editing the file:

```
set DATABASE_URL=postgresql+psycopg://irrigation:<your-password>@localhost:5432/smart_irrigation
scripts\db_upgrade.bat
```

### 4. Run the app

```
.venv\Scripts\uvicorn app.main:app --app-dir backend
```

with `DATABASE_URL` set (via `backend/.env` or the shell), same as above.

## Creating future migrations

Whenever `backend/app/db.py`'s SQLAlchemy models change (new table, new
column, etc.):

1. Make sure a Postgres instance is running and migrated to the current
   head (`docker compose up -d db`, then `scripts\db_upgrade.bat`).
2. Autogenerate a new revision by diffing the models against that database:

   ```
   set DATABASE_URL=postgresql+psycopg://irrigation:<your-password>@localhost:5432/smart_irrigation
   .venv\Scripts\python -m alembic -c backend\alembic.ini revision --autogenerate -m "describe the change"
   ```

3. **Always read the generated file** in `backend/migrations/versions/` —
   autogenerate is a diff tool, not an oracle; it can miss things (renamed
   columns look like a drop+add, for example) and needs a human to check
   both `upgrade()` and `downgrade()` before it's trusted.
4. Apply it (`scripts\db_upgrade.bat`) and commit the new revision file.

**Never edit a migration that's already been applied anywhere** (your own
Postgres, a teammate's, anything beyond your own machine before you've
committed). Alembic identifies revisions by their file's revision id, not
its contents — editing an applied migration silently desyncs whatever
database already ran the old version from what the file now says. If a
migration was wrong, write a new migration that corrects it.

## Why psycopg v3 over psycopg2-binary

CLAUDE.md rule 8 requires pinned, verified-installable dependencies for
Python 3.14. `psycopg2-binary==2.9.10` was tried first (per the original
Phase 9 brief) and failed:

```
Error: pg_config executable not found.
pg_config is required to build psycopg2 from source.
```

No prebuilt wheel exists yet for Python 3.14 on Windows, so pip falls back
to a source build that needs a local PostgreSQL install just to get
`pg_config` — not acceptable for a zero-friction dev setup. `psycopg[binary]
==3.2.10` installs from a prebuilt `cp314-win_amd64` wheel with no such
requirement, so that's what `backend/requirements.txt` pins. The only
consequence is the SQLAlchemy URL scheme: `postgresql+psycopg://` (v3)
instead of the classic `postgresql+psycopg2://` (v2) — noted everywhere a
Postgres URL appears in this doc.

## What's tested vs. what was verified manually

Per CLAUDE.md rule 2, the automated suite (`.venv\Scripts\python -m pytest
backend\tests -q`) stays entirely on SQLite — fast, and it never requires
Docker to be running:

- `backend/tests/test_database_url.py` — `resolve_database_url()`'s
  SQLite-default / `DATABASE_URL`-override behavior, plus `_build_engine()`
  produces the correct dialect/driver for both a `sqlite://` and a
  `postgresql+psycopg://` URL (the latter never opens a real connection —
  `create_engine()` is lazy, so this needs no live Postgres server).
- `backend/tests/test_alembic_migrations.py` — the actual Alembic chain
  (`backend/migrations/`) upgrades a genuinely fresh temp SQLite database to
  head, and every column on every current model (including Phase 6's
  `risk_score`/`risk_band`) is present afterward.

The real Postgres path (docker-compose `db` service healthy, `alembic
upgrade head` against it, a real `/api/v1/auth/register` +
`/api/v1/predict` round-trip, rows confirmed via `psql`) was verified
manually end-to-end during Phase 9 development — see PROGRESS.md's Phase 9
entry for the exact result. It isn't part of the automated suite because
CLAUDE.md rule 2's test command must stay Docker-free.
