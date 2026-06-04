#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
JOB_NAME="${PARKPULSE_LOOP_RESILIENCE_SCHEDULER_JOB:-parkpulse-operating-loop-resilience}"
SCHEDULE="${PARKPULSE_LOOP_RESILIENCE_SCHEDULE:-*/30 * * * *}"
TIME_ZONE="${PARKPULSE_LOOP_RESILIENCE_TIME_ZONE:-America/New_York}"
SCHEDULER_SA_NAME="${PARKPULSE_LOOP_RESILIENCE_SA:-parkpulse-loop-monitor}"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/schedule_operating_loop_resilience.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Install Google Cloud CLI first." >&2
  exit 127
fi

gcloud services enable cloudscheduler.googleapis.com iam.googleapis.com run.googleapis.com --project "$PROJECT_ID"

if ! gcloud iam service-accounts describe "$SCHEDULER_SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SCHEDULER_SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "ParkPulse operating-loop resilience monitor"
fi

gcloud run services add-iam-policy-binding "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --member "serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role roles/run.invoker \
  --quiet >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SCHEDULER_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$SCHEDULER_SA_EMAIL" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${SCHEDULER_AGENT}" \
  --role roles/iam.serviceAccountTokenCreator \
  --quiet >/dev/null || true

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
URI="${SERVICE_URL}/api/gcp/operating-loop-resilience?write_artifact=true"

if gcloud scheduler jobs describe "$JOB_NAME" --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB_NAME" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$URI" \
    --http-method GET \
    --oidc-service-account-email "$SCHEDULER_SA_EMAIL" \
    --oidc-token-audience "$SERVICE_URL" \
    --headers "Accept=application/json" \
    --quiet
else
  gcloud scheduler jobs create http "$JOB_NAME" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$URI" \
    --http-method GET \
    --oidc-service-account-email "$SCHEDULER_SA_EMAIL" \
    --oidc-token-audience "$SERVICE_URL" \
    --headers "Accept=application/json" \
    --quiet
fi

echo "Operating-loop resilience scheduler configured."
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE}"
echo "Job: ${JOB_NAME}"
echo "Schedule: ${SCHEDULE} (${TIME_ZONE})"
echo "URI: ${URI}"
