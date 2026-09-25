@echo off
REM Double-click wrapper for make_full_zip.ps1 - builds lehar-release-full.zip
REM at the project root. See that script for what's included/excluded.
REM
REM WARNING: lehar-release-full.zip CONTAINS SECRETS (backend\.env) -
REM share only privately, never upload publicly or commit.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_full_zip.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to build the full release zip - see the output above.
    pause
    exit /b 1
)
pause
