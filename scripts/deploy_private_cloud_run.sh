#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}"
SERVICE_ACCOUNT_NAME="${PARKPULSE_CLOUD_RUN_SA:-parkpulse-private-run}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DATASET="${BIGQUERY_DATASET:-parkpulse_analytics}"
MONGO_URI_RESOURCE_NAME="${PARKPULSE_MONGODB_SECRET:-parkpulse-mongodb-uri}"
MONGODB_DATABASE="${MONGODB_DATABASE:-parkpulse_ops}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/deploy_private_cloud_run.sh <gcp-project-id> [region]" >&2
  exit 2
fi

scripts/gcp_bootstrap_private.sh "$PROJECT_ID" "$REGION"

DEPLOY_ARGS=()
MONGO_OPTIONAL="true"
if gcloud secrets describe "$MONGO_URI_RESOURCE_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  DEPLOY_ARGS+=(--set-secrets "MONGODB_URI=${MONGO_URI_RESOURCE_NAME}:latest")
  MONGO_OPTIONAL="false"
fi

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source backend \
  --quiet \
  --service-account "$SERVICE_ACCOUNT_EMAIL" \
  --no-allow-unauthenticated \
  --min-instances "${PARKPULSE_CLOUD_RUN_MIN_INSTANCES:-2}" \
  --max-instances "${PARKPULSE_CLOUD_RUN_MAX_INSTANCES:-2}" \
  --memory "${PARKPULSE_CLOUD_RUN_MEMORY:-1Gi}" \
  --cpu "${PARKPULSE_CLOUD_RUN_CPU:-1}" \
  --timeout "${PARKPULSE_CLOUD_RUN_TIMEOUT:-300}" \
  --set-env-vars "^~^PARKPULSE_PRIVACY_MODE=private_cloud_run~GOOGLE_GENAI_USE_VERTEXAI=true~GOOGLE_CLOUD_PROJECT=${PROJECT_ID}~GOOGLE_CLOUD_LOCATION=${REGION}~GOOGLE_GENAI_API_VERSION=v1~GEMINI_MODEL=gemini-2.5-flash~GEMINI_MODEL_FALLBACKS=gemini-2.0-flash~PARKPULSE_OPERATOR_IMMEDIATE_FIRST=${PARKPULSE_OPERATOR_IMMEDIATE_FIRST:-true}~PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS=${PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS:-15}~PARKPULSE_GEMINI_REACTION_MAX_OUTPUT_TOKENS=${PARKPULSE_GEMINI_REACTION_MAX_OUTPUT_TOKENS:-1800}~PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER=gcp~ENABLE_BIGQUERY_ANALYTICS=true~PARKPULSE_LIVE_BIGQUERY=true~BIGQUERY_DATASET=${DATASET}~BIGQUERY_LOCATION=${BIGQUERY_LOCATION:-US}~BIGQUERY_AUTO_CREATE_TABLES=true~ENABLE_ARIZE_TRACING=false~PARKPULSE_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000~ENABLE_PARKPULSE_FCM=false~ENABLE_PARKPULSE_PSEUDO_FCM=true~PARKPULSE_FCM_GUEST_TOPIC=parkpulse-guest-app~PARKPULSE_FCM_WORKER_TOPIC=parkpulse-worker-device~PARKPULSE_MONGO_OPTIONAL=${MONGO_OPTIONAL}~PARKPULSE_LIVE_FEED_STORAGE=mongodb~PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS=${PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS:-30}~MONGODB_DATABASE=${MONGODB_DATABASE}~MONGODB_OPERATION_TIMEOUT_MS=${MONGODB_OPERATION_TIMEOUT_MS:-1500}~MONGODB_HOT_STATUS_CACHE_TTL_SECONDS=${MONGODB_HOT_STATUS_CACHE_TTL_SECONDS:-15}~MONGODB_USE_SRV_URI=${MONGODB_USE_SRV_URI:-true}" \
  "${DEPLOY_ARGS[@]}"

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1 || true)"
if [[ -n "$ACTIVE_ACCOUNT" ]]; then
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --member "user:${ACTIVE_ACCOUNT}" \
    --role roles/run.invoker \
    --quiet >/dev/null
fi

echo "Private Cloud Run service deployed:"
echo "$SERVICE_URL"
echo "Test with:"
echo "scripts/cloud_run_private_curl.sh ${PROJECT_ID} ${REGION} ${SERVICE} /readyz"
