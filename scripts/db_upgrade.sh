#!/usr/bin/env bash
# Applies all pending Alembic migrations to whatever database DATABASE_URL
# (or backend/.env's DATABASE_URL) points at - see docs/DATABASE.md.
# SQLite is fine to run this against too (it's just usually unnecessary
# there, since app startup's init_db() already creates a fresh SQLite
# dev DB via create_all()).
#
# Usage:
#   scripts/db_upgrade.sh
#   DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/smart_irrigation" scripts/db_upgrade.sh
#
# Run from anywhere - paths below are relative to this script's own location.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi

if [ ! -x "$PYTHON" ]; then
    echo "Could not find a virtual environment python at $PROJECT_ROOT/.venv - create it first:"
    echo "  python -m venv .venv"
    echo "  .venv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt"
    exit 1
fi

echo "Running \"alembic upgrade head\" (backend/migrations)..."
"$PYTHON" -m alembic -c "$PROJECT_ROOT/backend/alembic.ini" upgrade head
