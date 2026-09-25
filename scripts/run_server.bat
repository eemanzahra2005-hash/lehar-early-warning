@echo off
REM Phase 14: runs the local (no-Docker) dev server in the foreground of
REM whatever window launches this file. STARTUP-NO-DOCKER.bat / START.bat's
REM fallback path launch this via `start "LEHAR Server" /MIN ...` so it runs
REM in its own detached, minimized console - this file's own job is just to
REM cd to the project root and start uvicorn with output redirected to a log
REM file, so a stranger never has to read a scrolling console to know the
REM app is still alive. STOP.bat kills this by its window title.
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 > lehar-server.log 2>&1
