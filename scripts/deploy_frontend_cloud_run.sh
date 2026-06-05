#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
FRONTEND_SERVICE="${PARKPULSE_FRONTEND_CLOUD_RUN_SERVICE:-parkpulse-frontend}"
BACKEND_SERVICE="${PARKPULSE_BACKEND_CLOUD_RUN_SERVICE:-parkpulse-private-api}"
FRONTEND_SERVICE_ACCOUNT_NAME="${PARKPULSE_FRONTEND_CLOUD_RUN_SA:-parkpulse-frontend-run}"
FRONTEND_SERVICE_ACCOUNT_EMAIL="${FRONTEND_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BACKEND_URL="${PARKPULSE_API_URL:-}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/deploy_frontend_cloud_run.sh <gcp-project-id> [region]" >&2
  exit 2
fi

if [[ -z "$BACKEND_URL" ]]; then
  BACKEND_URL="$(gcloud run services describe "$BACKEND_SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format='value(status.url)')"
fi

if [[ -z "$BACKEND_URL" ]]; then
  echo "Could not resolve backend Cloud Run URL for ${BACKEND_SERVICE}." >&2
  exit 1
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com \
  --project "$PROJECT_ID" \
  --quiet >/dev/null

if ! gcloud iam service-accounts describe "$FRONTEND_SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$FRONTEND_SERVICE_ACCOUNT_NAME" \
    --project "$PROJECT_ID" \
    --display-name "ParkPulse frontend Cloud Run" \
    --quiet >/dev/null
fi

gcloud run services add-iam-policy-binding "$BACKEND_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --member "serviceAccount:${FRONTEND_SERVICE_ACCOUNT_EMAIL}" \
  --role roles/run.invoker \
  --quiet >/dev/null

gcloud run deploy "$FRONTEND_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source frontend \
  --quiet \
  --service-account "$FRONTEND_SERVICE_ACCOUNT_EMAIL" \
  --allow-unauthenticated \
  --min-instances "${PARKPULSE_FRONTEND_MIN_INSTANCES:-0}" \
  --max-instances "${PARKPULSE_FRONTEND_MAX_INSTANCES:-2}" \
  --concurrency "${PARKPULSE_FRONTEND_CONCURRENCY:-80}" \
  --memory "${PARKPULSE_FRONTEND_MEMORY:-512Mi}" \
  --cpu "${PARKPULSE_FRONTEND_CPU:-1}" \
  --timeout "${PARKPULSE_FRONTEND_TIMEOUT:-60}" \
  --set-env-vars "PARKPULSE_API_URL=${BACKEND_URL},PARKPULSE_API_IDENTITY_AUDIENCE=${BACKEND_URL}"

FRONTEND_URL="$(gcloud run services describe "$FRONTEND_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.url)')"

echo "ParkPulse frontend deployed:"
echo "$FRONTEND_URL"
echo "Frontend proxy target:"
echo "$BACKEND_URL"

if [[ "${PARKPULSE_SKIP_FRONTEND_SMOKE:-false}" != "true" ]]; then
  python3 scripts/verify_frontend_smoke.py --frontend-url "$FRONTEND_URL" --timeout "${PARKPULSE_FRONTEND_SMOKE_TIMEOUT:-20}"
fi
