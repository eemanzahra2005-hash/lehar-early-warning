#!/bin/sh
# Container entrypoint (Phase 13): apply database migrations, then serve.
#
# Runs on every container start, against whatever DATABASE_URL is set
# (Postgres via docker-compose.yml's "db" service, or a Render-provisioned
# Postgres). Alembic is idempotent — a fresh database gets the full schema,
# an up-to-date one is a no-op. Uses the same alembic.ini/migrations/ that
# scripts/db_upgrade.bat runs on a developer's host.
set -e

cd /app/backend

# LEHAR Phase 1: gated on RUN_MIGRATIONS (default true — set in
# backend/Dockerfile). Render's free tier gives no shell access, so running
# `alembic upgrade head` here, in the start command, is the ONLY way
# migrations get applied there. It stays a variable rather than an
# unconditional step so a deployment that applies migrations out-of-band —
# a separate job, a DBA, or a read-only replica that must never be migrated
# — can turn it off without forking this script.
RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Applying database migrations (alembic upgrade head)..."
    alembic upgrade head
else
    echo "RUN_MIGRATIONS=${RUN_MIGRATIONS} — skipping 'alembic upgrade head'."
fi

PORT="${PORT:-8000}"
# Phase 13.1: explicit, not just "no --workers flag happens to default to
# 1" — a RAM-constrained host (Render free tier, 512MB) can only afford a
# single worker process; --workers is passed explicitly so this can never
# silently regress if uvicorn's own default ever changes. Also explicitly
# no --reload here (never was) — the reloader spawns a second watcher
# process, which this deployment profile can't afford either. The default
# is set in backend/Dockerfile (ENV WEB_CONCURRENCY=1) and repeated here so
# the script is still correct when run outside that image.
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
echo "Starting LEHAR API on port ${PORT} (workers=${WEB_CONCURRENCY})..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers "${WEB_CONCURRENCY}"
