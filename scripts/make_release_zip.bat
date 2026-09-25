@echo off
REM Double-click wrapper for make_release_zip.ps1 — builds lehar-release.zip
REM at the project root. See that script for what's included/excluded.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_release_zip.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to build the release zip — see the output above.
    pause
    exit /b 1
)
pause
