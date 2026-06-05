#!/usr/bin/env bash
set -euo pipefail

EXTERNAL_ROOT="/Volumes/Backup drive /parkpulse-runtime/google-hackathon-y26"
LOG_DIR="$EXTERNAL_ROOT/logs"

mkdir -p "$LOG_DIR"

screen -S parkpulse-backend-external -X quit >/dev/null 2>&1 || true
screen -S parkpulse-spring-external -X quit >/dev/null 2>&1 || true
screen -S parkpulse-frontend-external -X quit >/dev/null 2>&1 || true

for port in 8000 8010 5174; do
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -n "$pid" ]]; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
done

screen -dmS parkpulse-backend-external bash -lc "cd '$EXTERNAL_ROOT/backend' && PORT=8000 PARKPULSE_FORCE_LAZY_ASGI=1 ./venv/bin/python -u lazy_dev_server.py >> '$LOG_DIR/backend.log' 2>&1"
FRONTEND_API_URL="http://127.0.0.1:8000"
if [[ -d "$EXTERNAL_ROOT/spring-backend" ]]; then
  screen -dmS parkpulse-spring-external bash -lc "cd '$EXTERNAL_ROOT' && PARKPULSE_PYTHON_BACKEND_URL=http://127.0.0.1:8000 scripts/run_spring_backend.sh >> '$LOG_DIR/spring-backend.log' 2>&1"
  FRONTEND_API_URL="http://127.0.0.1:8010"
fi
screen -dmS parkpulse-frontend-external bash -lc "cd '$EXTERNAL_ROOT/frontend' && NEXT_PUBLIC_API_URL=$FRONTEND_API_URL VITE_PARKPULSE_API_PROXY=$FRONTEND_API_URL npm run dev:local -- --host 127.0.0.1 --port 5174 >> '$LOG_DIR/frontend.log' 2>&1"

if [[ "$FRONTEND_API_URL" == "http://127.0.0.1:8010" ]]; then
  echo "Spring:   http://127.0.0.1:8010"
else
  echo "Spring:   not started; spring-backend directory not found"
fi
echo "Python:   http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5174"
