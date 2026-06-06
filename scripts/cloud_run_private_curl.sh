#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
PATH_NAME="${4:-/api/gcp-gemini/status}"
ROLE="${PARKPULSE_ROLE:-}"
ROLE_AUTH_RESOURCE_NAME="${PARKPULSE_ROLE_AUTH_SECRET_NAME:-parkpulse-role-auth-secret}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/cloud_run_private_curl.sh <gcp-project-id> [region] [service] [path]" >&2
  exit 2
fi

SERVICE_URL="${PARKPULSE_PRIVATE_VERIFY_URL:-${PARKPULSE_CLOUD_RUN_URL:-}}"
if [[ -z "$SERVICE_URL" ]]; then
  SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
fi
TOKEN="$(gcloud auth print-identity-token)"
ROLE_HEADERS=()

if [[ -n "$ROLE" ]]; then
  ROLE_SIGNING_VALUE="$(gcloud secrets versions access latest --secret "$ROLE_AUTH_RESOURCE_NAME" --project "$PROJECT_ID")"
  ROLE_TOKEN="$(PYTHONPATH="${ROOT_DIR}/backend" python3 - "$ROLE_SIGNING_VALUE" "$ROLE" <<'PY'
import sys

from park_role_access import sign_role_session

secret, role = sys.argv[1], sys.argv[2]
print(sign_role_session("cloud-run-validator", role, secret, issuer="parkpulse-cloud-run-curl"))
PY
)"
  ROLE_HEADERS=(-H "x-parkpulse-role: ${ROLE}" -H "x-parkpulse-role-token: ${ROLE_TOKEN}")
fi

if [[ ${#ROLE_HEADERS[@]} -gt 0 ]]; then
  curl -fsS \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/json" \
    "${ROLE_HEADERS[@]}" \
    "${SERVICE_URL}${PATH_NAME}"
else
  curl -fsS \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/json" \
    "${SERVICE_URL}${PATH_NAME}"
fi
