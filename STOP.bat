@echo off
REM LEHAR - Early-Warning and Irrigation Advisory - one-click stop (Phase 14).
REM Double-click this file. Stops whichever mode is currently running -
REM the Docker stack (started by START.bat) and/or the local no-Docker
REM Python server (started by START.bat's fallback or STARTUP-NO-DOCKER.bat)
REM - it's safe to run this even if neither is running, or if you're not
REM sure which mode you started. Your data is preserved either way (SQLite
REM file / Docker named volumes) - the next START.bat picks up right where
REM you left off. Run "docker compose down -v" yourself instead if you want
REM a totally clean slate (deletes the Postgres DB, Grafana settings, etc).

setlocal
cd /d "%~dp0"

echo ============================================================
echo  Stopping LEHAR
echo ============================================================
echo.

where docker >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 (
        echo Stopping Docker containers ^(if any are running^)...
        docker compose down
        echo.
    )
)

echo Stopping the local Python server ^(if running^)...
taskkill /FI "WINDOWTITLE eq LEHAR Server*" /T /F >nul 2>&1

echo.
echo Done. Everything has been stopped. Your data is preserved -
echo double-click START.bat to start again.
pause
