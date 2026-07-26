@echo off
REM Windows equivalent of run.sh - seed once, then serve with reload.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul

REM Use the project venv when the caller hasn't already activated one, so running
REM this script from a plain cmd prompt doesn't fall through to the system Python.
if "%VIRTUAL_ENV%"=="" if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat

REM Seed the bundled sample once. auth.db is the marker: init_auth() creates it on
REM the first run and it lives for the life of the install (app.db is never created
REM by anything - that old guard re-seeded on every launch).
if not exist data\auth.db (
    python -m app.main
    if errorlevel 1 exit /b 1
)

uvicorn app.main:app --reload --port 8000
