#!/usr/bin/env bash
set -euo pipefail

EXTERNAL_ROOT="/Volumes/Backup drive /parkpulse-runtime/google-hackathon-y26"
LOG_DIR="$EXTERNAL_ROOT/logs"

mkdir -p "$LOG_DIR"

screen -S parkpulse-backend-external -X quit >/dev/null 2>&1 || true
screen -S parkpulse-frontend-external -X quit >/dev/null 2>&1 || true

backend_pid="$(lsof -tiTCP:8000 -sTCP:LISTEN || true)"
if [[ -n "$backend_pid" ]]; then
  kill "$backend_pid" >/dev/null 2>&1 || true
fi

frontend_pid="$(lsof -tiTCP:5174 -sTCP:LISTEN || true)"
if [[ -n "$frontend_pid" ]]; then
  kill "$frontend_pid" >/dev/null 2>&1 || true
fi

screen -dmS parkpulse-backend-external bash -lc "cd '$EXTERNAL_ROOT/backend' && PORT=8000 ./venv/bin/python -u lazy_dev_server.py >> '$LOG_DIR/backend.log' 2>&1"
screen -dmS parkpulse-frontend-external bash -lc "cd '$EXTERNAL_ROOT/frontend' && NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev:local -- --host 127.0.0.1 --port 5174 >> '$LOG_DIR/frontend.log' 2>&1"

echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5174"
