@echo off
REM Applies all pending Alembic migrations to whatever database DATABASE_URL
REM (or backend/.env's DATABASE_URL) points at - see docs/DATABASE.md.
REM SQLite is fine to run this against too (it's just usually unnecessary
REM there, since app startup's init_db() already creates a fresh SQLite
REM dev DB via create_all()).
REM
REM Usage:
REM   scripts\db_upgrade.bat
REM   set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/smart_irrigation
REM   scripts\db_upgrade.bat
REM
REM Run from anywhere - paths below are relative to this script's own location.

setlocal

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo Could not find %PYTHON% - create the virtual environment first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
    exit /b 1
)

echo Running "alembic upgrade head" (backend\migrations)...
"%PYTHON%" -m alembic -c "%PROJECT_ROOT%\backend\alembic.ini" upgrade head
exit /b %ERRORLEVEL%
