# PowerShell equivalent of run.sh - seed once, then serve with reload.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

# Use the project venv when the caller hasn't already activated one, so running
# this script from a plain PowerShell prompt doesn't fall through to the system
# Python. Needs an unrestricted execution policy; see README if activation fails.
if (-not $env:VIRTUAL_ENV -and (Test-Path ".venv\Scripts\Activate.ps1")) {
    & ".venv\Scripts\Activate.ps1"
}

# Seed the bundled sample once. auth.db is the marker: init_auth() creates it on
# the first run and it lives for the life of the install (app.db is never created
# by anything - that old guard re-seeded on every launch).
if (-not (Test-Path "data\auth.db")) { python -m app.main }

uvicorn app.main:app --reload --port 8000
