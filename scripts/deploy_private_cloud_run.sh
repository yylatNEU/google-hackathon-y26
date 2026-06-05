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
MONGODB_MODEL_API_KEY_RESOURCE_NAME="${PARKPULSE_MONGODB_MODEL_API_KEY_SECRET:-parkpulse-mongodb-model-api-key}"
ROLE_AUTH_RESOURCE_NAME="${PARKPULSE_ROLE_AUTH_SECRET_NAME:-parkpulse-role-auth-secret}"
ROLE_ISSUER_RESOURCE_NAME="${PARKPULSE_ROLE_ISSUER_KEY_SECRET:-parkpulse-role-issuer-key}"
NO_TRAFFIC_DEPLOY="${PARKPULSE_DEPLOY_NO_TRAFFIC:-false}"
DEPLOY_TAG="${PARKPULSE_DEPLOY_TAG:-}"
RESTORE_NO_TRAFFIC_BASELINE="${PARKPULSE_RESTORE_NO_TRAFFIC_BASELINE:-true}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/deploy_private_cloud_run.sh <gcp-project-id> [region]" >&2
  exit 2
fi

scripts/preflight_private_cloud_run_source.sh
scripts/gcp_bootstrap_private.sh "$PROJECT_ID" "$REGION"

BASELINE_TRAFFIC_FILE="$(mktemp "${TMPDIR:-/tmp}/parkpulse-cloud-run-traffic.XXXXXX")"
BASELINE_TRAFFIC_CAPTURED="false"
if [[ "$NO_TRAFFIC_DEPLOY" == "true" && "$RESTORE_NO_TRAFFIC_BASELINE" == "true" ]]; then
  if gcloud run services describe "$SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json > "$BASELINE_TRAFFIC_FILE" 2>/dev/null; then
    BASELINE_TRAFFIC_CAPTURED="true"
  fi
fi

restore_no_traffic_baseline() {
  if [[ "$NO_TRAFFIC_DEPLOY" != "true" || "$RESTORE_NO_TRAFFIC_BASELINE" != "true" || "$BASELINE_TRAFFIC_CAPTURED" != "true" ]]; then
    return 0
  fi
  local baseline_revisions
  baseline_revisions="$(python3 - "$BASELINE_TRAFFIC_FILE" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
traffic = payload.get("status", {}).get("traffic", [])
parts = []
for row in traffic:
    percent = int(row.get("percent") or 0)
    revision = row.get("revisionName")
    if percent > 0 and revision:
        parts.append(f"{revision}={percent}")
print(",".join(parts))
PY
)"
  if [[ -n "$baseline_revisions" ]]; then
    gcloud run services update-traffic "$SERVICE" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --to-revisions "$baseline_revisions" \
      --quiet >/dev/null
  fi
}

CLOUD_RUN_EGRESS_IP="${PARKPULSE_CLOUD_RUN_EGRESS_IP:-$(gcloud compute addresses describe parkpulse-cloud-run-egress --project "$PROJECT_ID" --region "$REGION" --format='value(address)' 2>/dev/null || true)}"
DEPLOY_ARGS=()
MONGO_OPTIONAL="true"
if gcloud secrets describe "$MONGO_URI_RESOURCE_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  DEPLOY_ARGS+=(--set-secrets "MONGODB_URI=${MONGO_URI_RESOURCE_NAME}:latest")
  MONGO_OPTIONAL="false"
fi
if gcloud secrets describe "$MONGODB_MODEL_API_KEY_RESOURCE_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$MONGODB_MODEL_API_KEY_RESOURCE_NAME" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role roles/secretmanager.secretAccessor \
    --quiet >/dev/null || true
  DEPLOY_ARGS+=(--set-secrets "MONGODB_MODEL_API_KEY=${MONGODB_MODEL_API_KEY_RESOURCE_NAME}:latest")
fi
if gcloud secrets describe "$ROLE_AUTH_RESOURCE_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$ROLE_AUTH_RESOURCE_NAME" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role roles/secretmanager.secretAccessor \
    --quiet >/dev/null || true
  DEPLOY_ARGS+=(--set-secrets "PARKPULSE_ROLE_AUTH_SECRET=${ROLE_AUTH_RESOURCE_NAME}:latest")
fi
if gcloud secrets describe "$ROLE_ISSUER_RESOURCE_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$ROLE_ISSUER_RESOURCE_NAME" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role roles/secretmanager.secretAccessor \
    --quiet >/dev/null || true
  DEPLOY_ARGS+=(--set-secrets "PARKPULSE_ROLE_SESSION_ISSUER_KEY=${ROLE_ISSUER_RESOURCE_NAME}:latest")
fi

TRAFFIC_ARGS=()
if [[ "$NO_TRAFFIC_DEPLOY" == "true" ]]; then
  TRAFFIC_ARGS+=(--no-traffic)
fi
if [[ -n "$DEPLOY_TAG" ]]; then
  TRAFFIC_ARGS+=(--tag "$DEPLOY_TAG")
fi

deploy_service() {
  gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source backend \
  --quiet \
  --service-account "$SERVICE_ACCOUNT_EMAIL" \
  --no-allow-unauthenticated \
  --min-instances "${PARKPULSE_CLOUD_RUN_MIN_INSTANCES:-2}" \
  --max-instances "${PARKPULSE_CLOUD_RUN_MAX_INSTANCES:-4}" \
  --concurrency "${PARKPULSE_CLOUD_RUN_CONCURRENCY:-4}" \
  --memory "${PARKPULSE_CLOUD_RUN_MEMORY:-1Gi}" \
  --cpu "${PARKPULSE_CLOUD_RUN_CPU:-1}" \
  --timeout "${PARKPULSE_CLOUD_RUN_TIMEOUT:-300}" \
  --set-env-vars "^~^PARKPULSE_PRIVACY_MODE=private_cloud_run~PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION=${PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION:-true}~PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN=${PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN:-true}~GOOGLE_GENAI_USE_VERTEXAI=true~GOOGLE_CLOUD_PROJECT=${PROJECT_ID}~GOOGLE_CLOUD_LOCATION=${REGION}~GOOGLE_GENAI_API_VERSION=v1~GEMINI_MODEL=gemini-2.5-flash~GEMINI_MODEL_FALLBACKS=gemini-2.0-flash~PARKPULSE_OPERATOR_IMMEDIATE_FIRST=${PARKPULSE_OPERATOR_IMMEDIATE_FIRST:-true}~PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS=${PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS:-15}~PARKPULSE_GEMINI_REACTION_MAX_OUTPUT_TOKENS=${PARKPULSE_GEMINI_REACTION_MAX_OUTPUT_TOKENS:-1800}~PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER=gcp~ENABLE_GCP_CLOUD_TRACE_EXPORT=${ENABLE_GCP_CLOUD_TRACE_EXPORT:-true}~PARKPULSE_ENABLE_OTEL_SPANS=${PARKPULSE_ENABLE_OTEL_SPANS:-true}~GCP_TRACE_PROJECT=${GCP_TRACE_PROJECT:-${PROJECT_ID}}~ENABLE_VERTEX_GENAI_EVAL=${ENABLE_VERTEX_GENAI_EVAL:-true}~VERTEX_GENAI_EVALUATOR_ID=${VERTEX_GENAI_EVALUATOR_ID:-parkpulse-vertex-genai-eval}~PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER=${PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER:-true}~ENABLE_BIGQUERY_ANALYTICS=true~PARKPULSE_LIVE_BIGQUERY=true~BIGQUERY_DATASET=${DATASET}~BIGQUERY_LOCATION=${BIGQUERY_LOCATION:-US}~BIGQUERY_AUTO_CREATE_TABLES=true~PARKPULSE_MONGO_OPTIONAL=${MONGO_OPTIONAL}~PARKPULSE_COPILOT_HOT_PATH_LOCAL_ONLY=${PARKPULSE_COPILOT_HOT_PATH_LOCAL_ONLY:-true}~PARKPULSE_COPILOT_LATENCY_DIAGNOSTICS=${PARKPULSE_COPILOT_LATENCY_DIAGNOSTICS:-false}~PARKPULSE_COPILOT_LIGHTWEIGHT_PATH=${PARKPULSE_COPILOT_LIGHTWEIGHT_PATH:-true}~PARKPULSE_COPILOT_LIGHTWEIGHT_STATE_CACHE_ONLY=${PARKPULSE_COPILOT_LIGHTWEIGHT_STATE_CACHE_ONLY:-true}~PARKPULSE_COPILOT_LIGHTWEIGHT_MODEL_TIMEOUT_SECONDS=${PARKPULSE_COPILOT_LIGHTWEIGHT_MODEL_TIMEOUT_SECONDS:-4}~PARKPULSE_COPILOT_SEMANTIC_MEMORY=${PARKPULSE_COPILOT_SEMANTIC_MEMORY:-false}~PARKPULSE_COPILOT_SEMANTIC_MEMORY_TIMEOUT_SECONDS=${PARKPULSE_COPILOT_SEMANTIC_MEMORY_TIMEOUT_SECONDS:-2}~PARKPULSE_COPILOT_SEMANTIC_MEMORY_CACHE_POLICY=${PARKPULSE_COPILOT_SEMANTIC_MEMORY_CACHE_POLICY:-role_cache_only}~PARKPULSE_MONGO_MODEL_EMBEDDINGS=${PARKPULSE_MONGO_MODEL_EMBEDDINGS:-false}~MONGODB_MODEL_EMBEDDING_ENDPOINT=${MONGODB_MODEL_EMBEDDING_ENDPOINT:-https://ai.mongodb.com/v1/embeddings}~MONGODB_MODEL_EMBEDDING_MODEL=${MONGODB_MODEL_EMBEDDING_MODEL:-voyage-4-lite}~MONGODB_MODEL_EMBEDDING_DIMENSIONS=${MONGODB_MODEL_EMBEDDING_DIMENSIONS:-256}~MONGODB_MODEL_EMBEDDING_PATH=${MONGODB_MODEL_EMBEDDING_PATH:-modelEmbedding}~MONGODB_MODEL_EMBEDDING_TIMEOUT_SECONDS=${MONGODB_MODEL_EMBEDDING_TIMEOUT_SECONDS:-4}~MONGODB_MODEL_QUERY_EMBEDDING_CACHE_TTL_SECONDS=${MONGODB_MODEL_QUERY_EMBEDDING_CACHE_TTL_SECONDS:-60}~PARKPULSE_FAST_ROLE_SYNC_PERSIST=${PARKPULSE_FAST_ROLE_SYNC_PERSIST:-false}~PARKPULSE_ENABLE_GCP_ML_TRAINING=${PARKPULSE_ENABLE_GCP_ML_TRAINING:-true}~PARKPULSE_ENABLE_REAL_BQML_START=${PARKPULSE_ENABLE_REAL_BQML_START:-true}~PARKPULSE_ENABLE_LIVE_BQ_TABLE_VALIDATION=${PARKPULSE_ENABLE_LIVE_BQ_TABLE_VALIDATION:-true}~PARKPULSE_READINESS_LOAD_BQ_ROWS=${PARKPULSE_READINESS_LOAD_BQ_ROWS:-true}~PARKPULSE_READINESS_BQ_ROW_LIMIT=${PARKPULSE_READINESS_BQ_ROW_LIMIT:-80}~PARKPULSE_BQ_TABLE_VALIDATION_TIMEOUT_SECONDS=${PARKPULSE_BQ_TABLE_VALIDATION_TIMEOUT_SECONDS:-3}~PARKPULSE_BQML_START_TIMEOUT_SECONDS=${PARKPULSE_BQML_START_TIMEOUT_SECONDS:-10}~PARKPULSE_ACTUAL_TRAINING_STATUS_TIMEOUT_SECONDS=${PARKPULSE_ACTUAL_TRAINING_STATUS_TIMEOUT_SECONDS:-15}~PARKPULSE_CONTROLLED_TRAINING_GENERATION_TIMEOUT_SECONDS=${PARKPULSE_CONTROLLED_TRAINING_GENERATION_TIMEOUT_SECONDS:-120}~PARKPULSE_GCP_TRAINING_DRY_RUN_TIMEOUT_SECONDS=${PARKPULSE_GCP_TRAINING_DRY_RUN_TIMEOUT_SECONDS:-12}~PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH=${PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH:-data/customer_venue_export.sample.json}~PARKPULSE_ENABLE_DEV_ROLE_ISSUER=false~ENABLE_ARIZE_TRACING=false~PARKPULSE_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000~ENABLE_PARKPULSE_FCM=false~ENABLE_PARKPULSE_PSEUDO_FCM=true~PARKPULSE_FCM_GUEST_TOPIC=parkpulse-guest-app~PARKPULSE_FCM_WORKER_TOPIC=parkpulse-worker-device~PARKPULSE_LIVE_FEED_STORAGE=${PARKPULSE_LIVE_FEED_STORAGE:-mongodb}~PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS=${PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS:-30}~PARKPULSE_CLOUD_RUN_EGRESS_IP=${CLOUD_RUN_EGRESS_IP}~MONGODB_DATABASE=${MONGODB_DATABASE}~MONGODB_OPERATION_TIMEOUT_MS=${MONGODB_OPERATION_TIMEOUT_MS:-2500}~MONGODB_HOT_STATUS_CACHE_TTL_SECONDS=${MONGODB_HOT_STATUS_CACHE_TTL_SECONDS:-15}~MONGODB_USE_SRV_URI=${MONGODB_USE_SRV_URI:-true}" \
  "$@"
}

if [[ ${#TRAFFIC_ARGS[@]} -gt 0 ]]; then
  deploy_service "${TRAFFIC_ARGS[@]}" "${DEPLOY_ARGS[@]}"
else
  deploy_service "${DEPLOY_ARGS[@]}"
fi

if [[ "$NO_TRAFFIC_DEPLOY" != "true" ]]; then
  gcloud run services update-traffic "$SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --to-latest \
    --quiet
else
  restore_no_traffic_baseline
fi

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

if [[ "$NO_TRAFFIC_DEPLOY" != "true" && "${PARKPULSE_SKIP_DEPLOY_VERIFY:-false}" != "true" ]]; then
  scripts/verify_private_cloud_run_deploy.sh "$PROJECT_ID" "$REGION" "$SERVICE"
  scripts/verify_private_cloud_run_agent_roles.sh "$PROJECT_ID" "$REGION" "$SERVICE"
fi

echo "Private Cloud Run service deployed:"
echo "$SERVICE_URL"
if [[ "$NO_TRAFFIC_DEPLOY" == "true" ]]; then
  echo "No production traffic was changed."
  if [[ "$RESTORE_NO_TRAFFIC_BASELINE" == "true" && "$BASELINE_TRAFFIC_CAPTURED" == "true" ]]; then
    echo "Baseline traffic split was restored after no-traffic deploy."
  fi
  if [[ -n "$DEPLOY_TAG" ]]; then
    echo "Tagged revision: ${DEPLOY_TAG}"
  fi
fi
echo "Test with:"
echo "scripts/verify_private_cloud_run_deploy.sh ${PROJECT_ID} ${REGION} ${SERVICE}"
echo "scripts/verify_private_cloud_run_agent_roles.sh ${PROJECT_ID} ${REGION} ${SERVICE}"
