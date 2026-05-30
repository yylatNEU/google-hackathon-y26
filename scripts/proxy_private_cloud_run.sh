#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
PORT="${4:-8001}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/proxy_private_cloud_run.sh <gcp-project-id> [region] [service] [local-port]" >&2
  exit 2
fi

echo "Proxying private Cloud Run service to http://127.0.0.1:${PORT}"
echo "Run the frontend with: VITE_API_URL=http://127.0.0.1:${PORT} npm run dev"
exec python3 scripts/private_cloud_run_http_proxy.py \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service "$SERVICE" \
  --port "$PORT"
