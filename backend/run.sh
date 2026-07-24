#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
[ -f app.db ] || python -m app.main      # seed once
exec uvicorn app.main:app --reload --port 8000
