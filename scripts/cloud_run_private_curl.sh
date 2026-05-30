#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
PATH_NAME="${4:-/api/gcp-gemini/status}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/cloud_run_private_curl.sh <gcp-project-id> [region] [service] [path]" >&2
  exit 2
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
TOKEN="$(gcloud auth print-identity-token)"

curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/json" \
  "${SERVICE_URL}${PATH_NAME}"
