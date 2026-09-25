# Multi-stage production image for the FastAPI backend (Phase 11; wired
# into docker-compose.yml's "api" service and Render (docs/DEPLOY_RENDER.md)
# in Phase 13; slimmed for the 512MB free tier in LEHAR Phase 1). Also built
# on every CI push (a fast fail if a dependency stops installing cleanly).
#
# Build from the PROJECT ROOT (needs both backend/ and frontend/ in its
# context — the running app serves frontend/ as static files, see
# app/main.py's FRONTEND_DIR):
#   docker build -f backend/Dockerfile -t lehar-backend .
#
# Base image (LEHAR Phase 1): python:3.14-slim, matching the project's
# documented Python 3.14 environment (CLAUDE.md) and the interpreter the
# test suite runs on. A move to python:3.11-slim was evaluated and rejected
# on evidence, not preference: numpy==2.5.2 and shap==0.52.0 publish no
# cp311 wheel at all (numpy 2.5 requires >=3.12), so a 3.11 image cannot
# install this pinned set — and downgrading those pins would mean serving
# model.joblib artifacts pickled by a DIFFERENT scikit-learn/numpy than the
# one that wrote them, which is exactly the class of deploy-only breakage
# this phase exists to remove. Verified with:
#   pip download -r backend/requirements-deploy.txt --only-binary=:all: \
#     --python-version 3.14 --platform manylinux_2_17_x86_64 \
#     --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64
# -> 73 prebuilt manylinux wheels, zero source builds. See docs/MEMORY.md.

# --- Stage 1: builder — installs pinned deps into an isolated venv -------
FROM python:3.14-slim AS builder

WORKDIR /build

# Build tools for any dependency without a prebuilt manylinux wheel for this
# Python version yet; removed from the final runtime image below, so they
# don't bloat or widen the attack surface of what actually ships. Every pin
# in requirements-deploy.txt currently resolves to a prebuilt wheel, so this
# is a safety net for a future pin change rather than a current requirement.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# LEHAR Phase 1: requirements-DEPLOY.txt, not requirements.txt — the
# serving-only subset. It drops mlflow (the single heaviest dependency here,
# needed only by backend/ml/pipeline.py's training path) and pandera
# (training-dataset validation only). Dev/test dependencies
# (requirements-dev.txt: pytest, httpx, ruff, PyYAML) were never installed
# in this image and still aren't; torch has never been a dependency of this
# project at all. See requirements-deploy.txt's header for the full
# rationale and for what is deliberately KEPT.
COPY backend/requirements-deploy.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-deploy.txt

# --- Stage 2: runtime — slim image, no compilers, non-root user ----------
FROM python:3.14-slim AS runtime

# CLAUDE.md rules 4 + 13: every dataset/prediction in this app is synthetic
# research data — labeled here too, not just in the UI/docs, so the label
# travels with the shipped artifact.
LABEL org.opencontainers.image.description="LEHAR — Level-based Early-warning for Hydrological & Agricultural Risk (synthetic research data; research advisory, not an official warning)"

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- LEHAR Phase 1: 512MB production defaults ----------------------------
# Set in the image so they hold everywhere it runs (Render, `docker run`,
# compose) without depending on anyone remembering to pass them. Each is a
# plain environment variable, so a deployment that needs something different
# still overrides it — nothing here is hard-coded into the application
# (CLAUDE.md rule 3). Written as separate ENV instructions (env-only layers
# carry no size) so each value keeps the comment explaining it.

# One uvicorn worker. A second worker duplicates the entire interpreter, the
# sklearn/numpy/shap import cost and the loaded model — the largest single
# memory multiplier available, and unaffordable under 512MB. Read by
# backend/docker-entrypoint.sh.
ENV WEB_CONCURRENCY=1

# Lazy, memory-mapped model load; no eager SHAP warm-up at boot; SHAP skipped
# for models over LOW_MEMORY_SHAP_MAX_ESTIMATORS — see app/config.py's
# low_memory_mode docstring.
ENV LOW_MEMORY_MODE=true

# glibc allocates a per-thread arena (by default up to 8x the CPU count),
# each of which holds on to freed memory instead of returning it to the OS.
# Capping arenas at 2 trades a little allocator contention — irrelevant at
# one worker — for markedly less RSS retained after a burst of numpy/sklearn
# allocations, which is exactly what /predict produces.
ENV MALLOC_ARENA_MAX=2

# Render's free tier gives no shell access, so the entrypoint applies Alembic
# migrations itself before starting uvicorn. Set false where migrations are
# run out-of-band. See backend/docker-entrypoint.sh.
ENV RUN_MIGRATIONS=true

# Report the real environment in GET /api/v1/health instead of the local-dev
# default. render.yaml sets this too; having it here means a plain
# `docker run` of this image is honest about itself as well.
ENV ENVIRONMENT=production

WORKDIR /app

# backend/ (app code + trained model artifacts under ml/model/) and
# frontend/ (served as static files, see app/main.py) as siblings under
# /app — matches the exact relative layout every path in the codebase
# already assumes (FRONTEND_DIR, BASE_DIR, PROJECT_ROOT are all computed
# from __file__, so this is the only layout that works without code
# changes). .dockerignore excludes .venv/.env/.git/mlruns/__pycache__/the
# raw training CSV — none of those are needed to *serve* the app.
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Phase 13.1: on Render, drop every backend/ml/model/<version>/ directory
# except the one(s) actually served — keeps the deployed image lean (each
# trained version carries its own model.joblib, tens of MB). Render
# auto-translates a Docker-based service's envVars into build ARGs of the
# same name (see docs/DEPLOY_RENDER.md), so PRUNE_MODEL_VERSIONS/
# MODEL_VERSION here just need to be declared as ordinary envVars in
# render.yaml — no Render-specific build config needed. Defaults to a
# no-op: local `docker compose build`/`up` never sets these build args, so
# the local image keeps every version (all promote/rollback history stays
# testable there via the containerized "api" service), exactly as before
# this phase — see backend/ml/prune_unused_versions.py's docstring.
ARG PRUNE_MODEL_VERSIONS=false
ARG MODEL_VERSION=latest
RUN if [ "$PRUNE_MODEL_VERSIONS" = "true" ]; then \
        MODEL_VERSION="$MODEL_VERSION" python backend/ml/prune_unused_versions.py; \
    fi

RUN chown -R appuser:appuser /app \
    && chmod +x /app/backend/docker-entrypoint.sh
USER appuser

EXPOSE 8000

# Entrypoint applies Alembic migrations (when RUN_MIGRATIONS=true — see
# above) then starts uvicorn bound to $PORT (default 8000, see
# backend/docker-entrypoint.sh) — Phase 13's compose "api" service and
# Render both work from the same image unchanged.
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
