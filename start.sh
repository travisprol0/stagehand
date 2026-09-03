#!/usr/bin/env bash
set -euo pipefail

# Bootstrap stagehand and start the Django dev server.
#
# Optional env: HOST=127.0.0.1, PORT=8000
#
# Usage:
#   ./start.sh                 # venv, Postgres, migrate, runserver
#   ./start.sh --no-migrate      # skip migrate (db must already be current)
#   ./start.sh --collector       # also run collect_metrics in the background

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NO_MIGRATE=false
START_COLLECTOR=false
for arg in "$@"; do
  case "${arg}" in
    --no-migrate) NO_MIGRATE=true ;;
    --collector) START_COLLECTOR=true ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      echo "Run ./start.sh --help for usage." >&2
      exit 1
      ;;
  esac
done

PYTHON=""
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "ERROR: python3 required. Install Python 3.12+." >&2
  exit 1
fi

PIP="$ROOT/.venv/bin/pip"

echo ""
echo "============================================================"
echo "Python environment"
echo "============================================================"
echo ""

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Creating virtualenv at .venv ..."
  "$PYTHON" -m venv "$ROOT/.venv"
fi

PYTHON="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

echo "Installing Python dependencies ..."
"$PIP" install -q -r requirements.txt

if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
  echo "Creating .env from .env.example ..."
  cp "$ROOT/.env.example" "$ROOT/.env"
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
}

wait_for_db() {
  echo "Waiting for Postgres ..."
  for _ in $(seq 1 30); do
    if "$PYTHON" -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; then
      return
    fi
    sleep 1
  done
  echo "ERROR: Postgres did not become ready in time." >&2
  exit 1
}

echo ""
echo "============================================================"
echo "Database"
echo "============================================================"
echo ""

start_db
wait_for_db

if [[ "${NO_MIGRATE}" == false ]]; then
  echo ""
  echo "============================================================"
  echo "Migrations"
  echo "============================================================"
  echo ""
  "$PYTHON" manage.py migrate
fi

COLLECTOR_PID=""
cleanup() {
  if [[ -n "${COLLECTOR_PID}" ]]; then
    kill "${COLLECTOR_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ "${START_COLLECTOR}" == true ]]; then
  echo ""
  echo "Starting metrics collector in background ..."
  "$PYTHON" manage.py collect_metrics &
  COLLECTOR_PID=$!
fi

echo ""
echo "============================================================"
echo "Django dev server"
echo "============================================================"
echo ""
echo "Dashboard: http://${HOST}:${PORT}/"
echo "Health:    http://${HOST}:${PORT}/health/"
echo ""

exec "$PYTHON" manage.py runserver "${HOST}:${PORT}"
