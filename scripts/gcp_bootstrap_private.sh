#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE_ACCOUNT_NAME="${PARKPULSE_CLOUD_RUN_SA:-parkpulse-private-run}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DATASET="${BIGQUERY_DATASET:-parkpulse_analytics}"
PUBSUB_TOPIC="${PARKPULSE_PUBSUB_TOPIC:-parkpulse-ops-events}"
ENV_FILE="backend/.env"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/gcp_bootstrap_private.sh <gcp-project-id> [region]" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Install Google Cloud CLI first." >&2
  exit 127
fi

gcloud config set project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID" || true

if [[ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ]]; then
  echo "No Application Default Credentials found. Starting ADC login..."
  gcloud auth application-default login
  gcloud auth application-default set-quota-project "$PROJECT_ID" || true
fi

gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  eventarc.googleapis.com \
  fcm.googleapis.com \
  iam.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  workflowexecutions.googleapis.com \
  workflows.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
    --project "$PROJECT_ID" \
    --display-name "ParkPulse private Cloud Run runtime"
fi

for role in \
  roles/aiplatform.user \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser \
  roles/cloudtrace.agent \
  roles/logging.logWriter \
  roles/pubsub.publisher \
  roles/secretmanager.secretAccessor \
  roles/workflows.invoker; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "$role" \
    --quiet >/dev/null
done

if ! gcloud pubsub topics describe "$PUBSUB_TOPIC" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud pubsub topics create "$PUBSUB_TOPIC" --project "$PROJECT_ID"
fi

python3 - "$PROJECT_ID" "$DATASET" "${BIGQUERY_LOCATION:-US}" <<'PY'
import sys

from google.cloud import bigquery

project, dataset, location = sys.argv[1], sys.argv[2], sys.argv[3]
client = bigquery.Client(project=project)
dataset_id = f"{project}.{dataset}"
try:
    client.get_dataset(dataset_id)
except Exception:
    resource = bigquery.Dataset(dataset_id)
    resource.location = location
    client.create_dataset(resource, exists_ok=True)
PY

python3 - "$ENV_FILE" "$PROJECT_ID" "$REGION" "$DATASET" "$PUBSUB_TOPIC" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
project = sys.argv[2]
region = sys.argv[3]
dataset = sys.argv[4]
pubsub_topic = sys.argv[5]

updates = {
    "PARKPULSE_PRIVACY_MODE": "local_gcp_private",
    "PARKPULSE_ALLOWED_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000,http://0.0.0.0:3000",
    "GOOGLE_GENAI_USE_VERTEXAI": "true",
    "GOOGLE_CLOUD_PROJECT": project,
    "GOOGLE_CLOUD_LOCATION": region,
    "GOOGLE_GENAI_API_VERSION": "v1",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_MODEL_FALLBACKS": "gemini-2.0-flash",
    "PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER": "gcp",
    "ENABLE_BIGQUERY_ANALYTICS": "true",
    "BIGQUERY_DATASET": dataset,
    "BIGQUERY_LOCATION": "US",
    "BIGQUERY_AUTO_CREATE_TABLES": "true",
    "ENABLE_GCP_CLOUD_TRACE_EXPORT": "true",
    "PARKPULSE_ENABLE_OTEL_SPANS": "true",
    "GCP_TRACE_PROJECT": project,
    "ENABLE_VERTEX_GENAI_EVAL": "true",
    "VERTEX_GENAI_EVALUATOR_ID": "parkpulse-vertex-genai-eval",
    "PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER": "true",
    "PARKPULSE_CONTROLLED_TRAINING_GENERATION_TIMEOUT_SECONDS": "120",
    "ENABLE_PARKPULSE_PUBSUB": "true",
    "PARKPULSE_PUBSUB_TOPIC": pubsub_topic,
    "ENABLE_PARKPULSE_FCM": "false",
    "ENABLE_PARKPULSE_PSEUDO_FCM": "true",
    "PARKPULSE_FCM_GUEST_TOPIC": "parkpulse-guest-app",
    "PARKPULSE_FCM_WORKER_TOPIC": "parkpulse-worker-device",
    "ENABLE_PARKPULSE_WORKFLOWS": "false",
    "PARKPULSE_WORKFLOW_LOCATION": region,
    "PARKPULSE_WORKFLOW_ID": "parkpulse-operator-approval",
    "PARKPULSE_WORKFLOW_AUTO_APPROVE": "false",
    "PARKPULSE_WORKFLOW_CALLBACK_URL": "",
    "ENABLE_ARIZE_TRACING": "false",
}

lines = env_path.read_text().splitlines() if env_path.exists() else []
seen = set()
new_lines = []
for line in lines:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        new_lines.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        new_lines.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        new_lines.append(line)

for key, value in updates.items():
    if key not in seen:
        new_lines.append(f"{key}={value}")

env_path.write_text("\n".join(new_lines) + "\n")
PY

echo "Private GCP bootstrap complete."
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Runtime service account: ${SERVICE_ACCOUNT_EMAIL}"
echo "Pub/Sub topic: ${PUBSUB_TOPIC}"
echo "Local env updated: ${ENV_FILE}"
