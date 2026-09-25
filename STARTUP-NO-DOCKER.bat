@echo off
REM LEHAR - Early-Warning and Irrigation Advisory - no-Docker fallback (Phase 14).
REM Double-click this file. Uses ONLY Python - no Docker, no Postgres, no
REM Ollama. Creates a virtual environment, installs the app's dependencies,
REM runs it against a local SQLite database, and opens your browser.
REM This is also what START.bat runs automatically when Docker Desktop
REM isn't installed or isn't running.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  LEHAR - starting (Python-only mode)
echo  Early-Warning and Irrigation Advisory for Pakistan
echo ============================================================
echo.
echo No Docker, no Postgres, no Ollama needed for this mode. The app will
echo use a local SQLite database file instead.
echo.

REM ---------------------------------------------------------------
REM 1. Find a usable Python (3.11 or newer)
REM ---------------------------------------------------------------
echo Checking for Python...
set "PYEXE="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYEXE=py -3"
)
if "!PYEXE!"=="" (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYEXE=python"
    )
)

if "!PYEXE!"=="" (
    echo.
    echo [ERROR] Python was not found on this computer.
    echo.
    echo         FIX: install Python 3.12 from this link, then run this
    echo         file again:
    echo             https://www.python.org/downloads/
    echo.
    echo         IMPORTANT: on the first install screen, tick the box that
    echo         says "Add python.exe to PATH" before clicking Install.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('!PYEXE! --version 2^>^&1') do set "PYVERSTR=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVERSTR!") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
set "PYOK=1"
if !PYMAJOR! LSS 3 set "PYOK=0"
if !PYMAJOR! EQU 3 if !PYMINOR! LSS 11 set "PYOK=0"

if "!PYOK!"=="0" (
    echo.
    echo [ERROR] Found Python !PYVERSTR!, but this app needs Python 3.11 or newer.
    echo.
    echo         FIX: install a newer Python from this link, then run this
    echo         file again:
    echo             https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo Found Python !PYVERSTR! - good.
echo.

REM ---------------------------------------------------------------
REM 2. Create backend\.env (and root .env) with a random secret if missing
REM ---------------------------------------------------------------
echo Checking configuration...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ensure_env.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Could not create the .env configuration file.
    echo         FIX: make sure "backend\.env.example" exists in this folder,
    echo         then run this file again.
    pause
    exit /b 1
)
echo.

REM ---------------------------------------------------------------
REM 3. Create the virtual environment (first run only)
REM ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python for this app - first run only...
    !PYEXE! -m venv .venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Could not create the Python virtual environment.
        echo         FIX: make sure Python installed correctly ^(try
        echo         reinstalling from https://www.python.org/downloads/^),
        echo         then run this file again.
        pause
        exit /b 1
    )
)

REM ---------------------------------------------------------------
REM 4. Install dependencies (first run only, or if requirements changed)
REM ---------------------------------------------------------------
echo Installing required packages (first run only - this can take a few
echo minutes; later runs start in seconds)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet >"lehar-setup.log" 2>&1
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" --quiet >>"lehar-setup.log" 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Installing dependencies failed.
    echo         FIX: check your internet connection, then run this file
    echo         again. Full details were saved to: lehar-setup.log
    pause
    exit /b 1
)
echo Dependencies ready.
echo.

REM ---------------------------------------------------------------
REM 5. Start the app in the background and wait for it to be ready
REM ---------------------------------------------------------------
echo Starting the app...
del /q lehar-server.log >nul 2>&1
start "LEHAR Server" /MIN "%~dp0scripts\run_server.bat"

echo Loading model and getting ready (this can take up to a minute the
echo first time)...
set ATTEMPTS=0
:waitloop
set /a ATTEMPTS+=1
curl -s -o nul -m 3 "http://127.0.0.1:8000/api/v1/health"
if not errorlevel 1 goto ready
if !ATTEMPTS! GEQ 60 (
    echo.
    echo [WARNING] The app didn't respond after 5 minutes.
    echo           FIX: open lehar-server.log in this folder for details.
    echo           Opening the browser anyway - it may need a moment.
    goto openbrowser
)
REM ping-based delay (not `timeout`) - `timeout` refuses to run at all
REM ("Input redirection is not supported") when stdin isn't a real console,
REM which happens in some launch contexts; `ping` has no such requirement.
ping -n 6 127.0.0.1 >nul
goto waitloop

:ready
echo App is ready.
echo.

:openbrowser
echo ============================================================
echo  Ready. Opening your browser...
echo    App: http://localhost:8000
echo.
echo  This window can be closed - the app keeps running in the
echo  background. To stop it, double-click STOP.bat.
echo ============================================================
start "" "http://localhost:8000"

pause
