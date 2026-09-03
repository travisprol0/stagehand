#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

start_db() {
  if docker compose ps --status running db 2>/dev/null | grep -q db; then
    echo "Postgres already running (docker compose)."
    return
  fi
  echo "Starting Postgres on localhost:5433 ..."
  if docker compose up -d db; then
    :
  else
    echo "Retrying with sudo (docker socket not accessible) ..."
    sudo docker compose up -d db
  fi
  echo "Waiting for Postgres..."
  for _ in $(seq 1 30); do
    if .venv/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; then
      return
    fi
    sleep 1
  done
  echo "Postgres did not become ready in time." >&2
  exit 1
}

start_db
.venv/bin/python manage.py migrate
echo ""
echo "Ready. Run:"
echo "  source .venv/bin/activate && python manage.py runserver"
