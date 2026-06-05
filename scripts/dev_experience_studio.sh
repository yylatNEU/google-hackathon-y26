#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${PARKPULSE_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PARKPULSE_FRONTEND_PORT:-5173}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

if lsof -ti "tcp:${BACKEND_PORT}" >/dev/null 2>&1; then
  echo "Port ${BACKEND_PORT} is already in use. Stop the existing backend or set PARKPULSE_BACKEND_PORT." >&2
  exit 1
fi
if lsof -ti "tcp:${FRONTEND_PORT}" >/dev/null 2>&1; then
  echo "Port ${FRONTEND_PORT} is already in use. Stop the existing frontend or set PARKPULSE_FRONTEND_PORT." >&2
  exit 1
fi

(
  cd "${ROOT_DIR}/backend"
  HOST=127.0.0.1 PORT="${BACKEND_PORT}" PARKPULSE_FORCE_LAZY_ASGI=1 python3 -u lazy_dev_server.py
) &
BACKEND_PID=$!

(
  cd "${ROOT_DIR}/frontend"
  VITE_API_URL="http://127.0.0.1:${BACKEND_PORT}" npm run dev:local -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo "Experience Studio dev stack is running."
echo "Backend: http://127.0.0.1:${BACKEND_PORT}"
echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}/experience-studio"
echo "Memory verify: python3 scripts/verify_experience_studio_demo.py --base-url http://127.0.0.1:${BACKEND_PORT}"
echo "Press Ctrl-C to stop both processes."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
done

wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
