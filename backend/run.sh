#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env

# Use the project venv when the caller hasn't already activated one, so running
# this script from a plain shell doesn't fall through to the system Python.
if [ -z "$VIRTUAL_ENV" ] && [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Seed the bundled sample once. auth.db is the marker: init_auth() creates it on
# the first run and it lives for the life of the install (app.db is never created
# by anything -- that old guard re-seeded on every launch).
[ -f data/auth.db ] || python -m app.main

exec uvicorn app.main:app --reload --port 8000
