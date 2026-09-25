#!/bin/sh
# LEHAR — one-command local start (Phase 13), macOS/Linux
# equivalent of START.bat. Builds + starts the full Docker Compose stack
# (api, db, mlflow, prometheus, grafana), waits for the API to report
# healthy, then opens it in your default browser.
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo " LEHAR - starting local stack"
echo "============================================================"
echo

if [ ! -f ".env" ]; then
    echo "[ERROR] No .env file found in this folder."
    echo "        Copy .env.example to .env and set JWT_SECRET first -"
    echo "        see RUN-ME-FIRST.txt."
    exit 1
fi

# Phase 15.2: backend/.env holds the app's own settings (incl. the AI
# assistant's LLM_CLOUD_API_KEY) and docker-compose.yml loads it into the api
# container. Optional - the stack starts without it, the assistant is just off.
if [ ! -f "backend/.env" ]; then
    echo "[INFO] No backend/.env - the AI assistant will stay offline."
    echo "       To enable it: cp backend/.env.example backend/.env, set"
    echo "       LLM_CLOUD_API_KEY=... there, then run this script again."
    echo
fi

echo "Checking Docker..."
if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker doesn't seem to be running."
    echo "        Please start Docker Desktop (or the Docker daemon), then"
    echo "        run this script again."
    exit 1
fi
echo "Docker is running."
echo

echo "Building and starting containers (first run downloads images and"
echo "installs Python dependencies - this can take several minutes)..."
docker compose up --build -d
echo

APP_PORT=$(grep -E '^PORT=' .env 2>/dev/null | head -1 | cut -d= -f2)
APP_PORT=${APP_PORT:-8000}

echo "Waiting for the API to become healthy (migrations + model load)..."
# Polls the app's own health endpoint directly rather than `docker inspect`
# — this is the actual thing that matters (can the app be reached), and
# avoids depending on the Docker CLI's healthcheck reporting at all.
attempts=0
ready=0
while [ "$attempts" -lt 60 ]; do
    if curl -s -o /dev/null -m 3 "http://127.0.0.1:${APP_PORT}/api/v1/health"; then
        ready=1
        break
    fi
    attempts=$((attempts + 1))
    sleep 5
done

if [ "$ready" -eq 1 ]; then
    echo "API is healthy."
else
    echo
    echo "[WARNING] The API didn't respond after 5 minutes."
    echo "          Check the logs with: docker compose logs api"
    echo "          Opening the browser anyway - it may need a moment."
fi
echo

echo "============================================================"
echo " Smart Irrigation is running:"
echo "   App:        http://localhost:${APP_PORT}"
echo "   MLflow:     http://127.0.0.1:5000"
echo "   Prometheus: http://127.0.0.1:9090"
echo "   Grafana:    http://127.0.0.1:3000  (user: admin)"
echo
echo " To stop everything: docker compose down"
echo "============================================================"

URL="http://localhost:${APP_PORT}"
if command -v open >/dev/null 2>&1; then
    open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
else
    echo "Open $URL in your browser."
fi
