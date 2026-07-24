@echo off
REM Windows equivalent of run.sh — seed once, then serve with reload.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
if not exist app.db (
    python -m app.main
    if errorlevel 1 exit /b 1
)
uvicorn app.main:app --reload --port 8000
