#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
PORT="${PORT:-8000}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/run_local_gcp.sh <gcp-project-id> [region]" >&2
  exit 2
fi

scripts/gcp_bootstrap_private.sh "$PROJECT_ID" "$REGION"

cd backend
exec python3 -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --reload
