#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
TOPIC="${PARKPULSE_PUBSUB_TOPIC:-parkpulse-ops-events}"
WORKFLOW_ID="${PARKPULSE_WORKFLOW_ID:-parkpulse-operator-approval}"
WORKFLOW_SOURCE="${PARKPULSE_WORKFLOW_SOURCE:-infra/workflows/parkpulse-operator-approval.yaml}"
TRIGGER_NAME="${PARKPULSE_EVENTARC_TRIGGER:-parkpulse-ops-signal}"
TRIGGER_SA_NAME="${PARKPULSE_EVENTARC_SA:-parkpulse-eventarc-trigger}"
TRIGGER_SA_EMAIL="${TRIGGER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/deploy_gcp_operations.sh <gcp-project-id> [region] [cloud-run-service]" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Install Google Cloud CLI first." >&2
  exit 127
fi

if [[ ! -f "$WORKFLOW_SOURCE" ]]; then
  echo "Workflow source not found: ${WORKFLOW_SOURCE}" >&2
  exit 2
fi

gcloud config set project "$PROJECT_ID"

gcloud services enable \
  eventarc.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  workflowexecutions.googleapis.com \
  workflows.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud pubsub topics describe "$TOPIC" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud pubsub topics create "$TOPIC" --project "$PROJECT_ID"
fi

gcloud workflows deploy "$WORKFLOW_ID" \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --source "$WORKFLOW_SOURCE"

if ! gcloud iam service-accounts describe "$TRIGGER_SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$TRIGGER_SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "ParkPulse Eventarc trigger invoker"
fi

for role in roles/eventarc.eventReceiver roles/pubsub.subscriber; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${TRIGGER_SA_EMAIL}" \
    --role "$role" \
    --quiet >/dev/null
done

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"

gcloud run services add-iam-policy-binding "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --member "serviceAccount:${TRIGGER_SA_EMAIL}" \
  --role "roles/run.invoker" \
  --quiet >/dev/null

gcloud run services update "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "^~^ENABLE_PARKPULSE_PUBSUB=true~PARKPULSE_PUBSUB_TOPIC=${TOPIC}~ENABLE_PARKPULSE_WORKFLOWS=true~PARKPULSE_WORKFLOW_LOCATION=${REGION}~PARKPULSE_WORKFLOW_ID=${WORKFLOW_ID}~PARKPULSE_WORKFLOW_AUTO_APPROVE=false~PARKPULSE_WORKFLOW_CALLBACK_URL=${SERVICE_URL}/api/park/delivery/acknowledge~ENABLE_PARKPULSE_FCM=${ENABLE_PARKPULSE_FCM:-false}~ENABLE_PARKPULSE_PSEUDO_FCM=${ENABLE_PARKPULSE_PSEUDO_FCM:-true}~PARKPULSE_FCM_GUEST_TOPIC=${PARKPULSE_FCM_GUEST_TOPIC:-parkpulse-guest-app}~PARKPULSE_FCM_WORKER_TOPIC=${PARKPULSE_FCM_WORKER_TOPIC:-parkpulse-worker-device}~PARKPULSE_LIVE_BIGQUERY=true" \
  --quiet >/dev/null

if gcloud eventarc triggers describe "$TRIGGER_NAME" --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  gcloud eventarc triggers update "$TRIGGER_NAME" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --destination-run-service "$SERVICE" \
    --destination-run-region "$REGION" \
    --destination-run-path /api/gcp/eventarc/park-signal \
    --service-account "$TRIGGER_SA_EMAIL"
else
  gcloud eventarc triggers create "$TRIGGER_NAME" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --destination-run-service "$SERVICE" \
    --destination-run-region "$REGION" \
    --destination-run-path /api/gcp/eventarc/park-signal \
    --event-filters type=google.cloud.pubsub.topic.v1.messagePublished \
    --transport-topic "projects/${PROJECT_ID}/topics/${TOPIC}" \
    --service-account "$TRIGGER_SA_EMAIL"
fi

echo "ParkPulse GCP operations deployed."
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Pub/Sub topic: ${TOPIC}"
echo "Workflow: ${WORKFLOW_ID}"
echo "Eventarc trigger: ${TRIGGER_NAME}"
echo "Cloud Run service: ${SERVICE}"
echo "Cloud Run URL: ${SERVICE_URL}"
