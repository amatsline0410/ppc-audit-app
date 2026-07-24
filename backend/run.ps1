# PowerShell equivalent of run.sh — seed once, then serve with reload.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if (-not (Test-Path "app.db")) { python -m app.main }

uvicorn app.main:app --reload --port 8000
