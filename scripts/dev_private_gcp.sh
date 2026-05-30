#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
API_PORT="${PARKPULSE_PRIVATE_PROXY_PORT:-8001}"
FRONTEND_PORT="${PARKPULSE_FRONTEND_PORT:-3000}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/dev_private_gcp.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

cleanup() {
  if [[ -n "${PROXY_PID:-}" ]]; then kill "$PROXY_PID" 2>/dev/null || true; fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

if lsof -ti "tcp:${API_PORT}" >/dev/null 2>&1; then
  echo "Port ${API_PORT} is already in use. Stop the existing proxy or set PARKPULSE_PRIVATE_PROXY_PORT." >&2
  exit 1
fi
if lsof -ti "tcp:${FRONTEND_PORT}" >/dev/null 2>&1; then
  echo "Port ${FRONTEND_PORT} is already in use. Stop the existing frontend or set PARKPULSE_FRONTEND_PORT." >&2
  exit 1
fi

python3 scripts/private_cloud_run_http_proxy.py \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service "$SERVICE" \
  --port "$API_PORT" &
PROXY_PID=$!

(
  cd frontend
  VITE_API_URL="http://127.0.0.1:${API_PORT}" npm run dev:local -- --host 0.0.0.0 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "Private GCP dev stack is running."
echo "Frontend: http://localhost:${FRONTEND_PORT}"
echo "Private API proxy: http://127.0.0.1:${API_PORT}"
echo "Cloud Run service: ${SERVICE} (${PROJECT_ID}/${REGION})"
echo "Press Ctrl-C to stop both processes."

while kill -0 "$PROXY_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
done

wait "$PROXY_PID" "$FRONTEND_PID" 2>/dev/null || true
