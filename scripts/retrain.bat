@echo off
REM Runs the Phase 7 staged training pipeline end to end (see docs/MLOPS.md).
REM
REM Usage:
REM   scripts\retrain.bat                 train a candidate on the existing dataset
REM   scripts\retrain.bat --regenerate    rebuild the synthetic dataset first, then train
REM
REM Exit code is 0 if the quality gate PASSED (a new production version was
REM saved), nonzero if it FAILED (the current production model is untouched).
REM Run from the project root, or anywhere - paths below are relative to this
REM script's own location.

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

if "%~1"=="--regenerate" (
    echo Regenerating the synthetic dataset...
    "%PYTHON%" "%PROJECT_ROOT%\backend\ml\generate_data.py"
    if errorlevel 1 exit /b 1
)

echo Running the training pipeline (backend\ml\pipeline.py)...
"%PYTHON%" "%PROJECT_ROOT%\backend\ml\pipeline.py"
exit /b %ERRORLEVEL%
