@echo off
REM LEHAR - Early-Warning and Irrigation Advisory - one-click local start (Phase 14).
REM Double-click this file. No setup needed first - it creates its own
REM configuration automatically. Uses Docker Desktop if it's installed and
REM running (full stack: app, database, model tracking, monitoring);
REM otherwise it automatically falls back to a Python-only mode with a
REM local SQLite database (same as double-clicking STARTUP-NO-DOCKER.bat).

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  LEHAR - starting
echo  Early-Warning and Irrigation Advisory for Pakistan
echo ============================================================
echo.

echo Checking your computer...
echo Setting up configuration (first run only)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ensure_env.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Could not create the .env configuration file.
    echo         FIX: make sure this folder still contains ".env.example"
    echo         and "backend\.env.example", then run this file again.
    pause
    exit /b 1
)
echo.

REM ---------------------------------------------------------------
REM Decide which mode to use: Docker (full stack) if Docker Desktop is
REM installed AND running, otherwise fall back to the Python-only mode
REM automatically - a stranger never has to choose.
REM ---------------------------------------------------------------
set "USE_DOCKER=0"
where docker >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 set "USE_DOCKER=1"
)

if "!USE_DOCKER!"=="0" (
    echo Docker Desktop was not found running on this computer.
    echo Using the no-install Python mode instead ^(same as
    echo STARTUP-NO-DOCKER.bat^) - this is completely normal and still
    echo gives you the full app.
    echo.
    call "%~dp0STARTUP-NO-DOCKER.bat"
    exit /b !errorlevel!
)

echo Docker is running - using the full stack ^(app + database +
echo monitoring^).
echo.

for /f "tokens=2 delims==" %%p in ('findstr /b "PORT=" .env 2^>nul') do set APP_PORT=%%p
if "%APP_PORT%"=="" set APP_PORT=8000

echo Starting database...
echo Building and starting containers ^(first run downloads images and
echo installs dependencies - this can take several minutes; later runs
echo start in seconds^)...
docker compose up --build -d
if errorlevel 1 (
    echo.
    echo [ERROR] docker compose up failed - see the output above.
    echo         FIX: make sure Docker Desktop is fully started ^(it should
    echo         say "Docker Desktop is running"^), then run this file
    echo         again. If it keeps failing, see RUN-ME-FIRST.txt.
    pause
    exit /b 1
)
echo.

echo Loading model and getting ready ^(migrations + model load - this can
echo take up to a minute^)...
REM Polls the app's own health endpoint with curl (built into Windows 10/11)
REM rather than `docker inspect` - Docker Desktop's CLI can refuse to run
REM ("Input redirection is not supported") in some non-interactive console
REM contexts, but curl against a plain HTTP endpoint has no such quirk, and
REM this is the actual thing that matters: can the app be reached.
set ATTEMPTS=0
:waitloop
set /a ATTEMPTS+=1
curl -s -o nul -m 3 "http://127.0.0.1:%APP_PORT%/api/v1/health"
if not errorlevel 1 goto ready
if !ATTEMPTS! GEQ 60 (
    echo.
    echo [WARNING] The API didn't respond after 5 minutes.
    echo           FIX: check the logs with: docker compose logs api
    echo           Opening the browser anyway - it may need a moment.
    goto openbrowser
)
REM ping-based delay (not `timeout`) - `timeout` refuses to run at all
REM ("Input redirection is not supported") when stdin isn't a real console,
REM which happens in some launch contexts; `ping` has no such requirement.
ping -n 6 127.0.0.1 >nul
goto waitloop

:ready
echo API is healthy.
echo.

:openbrowser

echo ============================================================
echo  Ready. Opening your browser...
echo    App:        http://localhost:%APP_PORT%
echo    MLflow:     http://127.0.0.1:5000
echo    Prometheus: http://127.0.0.1:9090
echo    Grafana:    http://127.0.0.1:3000  ^(user: admin^)
echo.
echo  To stop everything, double-click STOP.bat.
echo ============================================================
start "" "http://localhost:%APP_PORT%"

pause
