#!/usr/bin/env bash
# Runs the Phase 7 staged training pipeline end to end (see docs/MLOPS.md).
#
# Usage:
#   scripts/retrain.sh                 train a candidate on the existing dataset
#   scripts/retrain.sh --regenerate    rebuild the synthetic dataset first, then train
#
# Exit code is 0 if the quality gate PASSED (a new production version was
# saved), nonzero if it FAILED (the current production model is untouched).
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

if [ "${1:-}" = "--regenerate" ]; then
    echo "Regenerating the synthetic dataset..."
    "$PYTHON" "$PROJECT_ROOT/backend/ml/generate_data.py"
fi

echo "Running the training pipeline (backend/ml/pipeline.py)..."
"$PYTHON" "$PROJECT_ROOT/backend/ml/pipeline.py"
