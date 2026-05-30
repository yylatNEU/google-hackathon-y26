#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
LOCATION="${2:-${GOOGLE_CLOUD_LOCATION:-global}}"
ENGINE_ID="${3:-${GEMINI_ENTERPRISE_ENGINE_ID:-}}"
ASSISTANT_ID="${4:-${GEMINI_ENTERPRISE_ASSISTANT_ID:-}}"
COLLECTION_ID="${GEMINI_ENTERPRISE_COLLECTION_ID:-default_collection}"
ENV_FILE="backend/.env"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/enable_gemini_enterprise.sh <gcp-project-id> [location] [engine-id] [assistant-id]" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Install Google Cloud CLI first:" >&2
  echo "https://cloud.google.com/sdk/docs/install" >&2
  exit 127
fi

gcloud config set project "$PROJECT_ID"
gcloud auth application-default set-quota-project "$PROJECT_ID" || true
gcloud services enable discoveryengine.googleapis.com --project "$PROJECT_ID"

if [[ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ]]; then
  echo "No Application Default Credentials found. Starting ADC login..."
  gcloud auth application-default login
  gcloud auth application-default set-quota-project "$PROJECT_ID" || true
fi

python3 - "$ENV_FILE" "$PROJECT_ID" "$LOCATION" "$COLLECTION_ID" "$ENGINE_ID" "$ASSISTANT_ID" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
project = sys.argv[2]
location = sys.argv[3]
collection = sys.argv[4]
engine = sys.argv[5]
assistant = sys.argv[6]

updates = {
    "AEROBRIDGE_AGENT_PLATFORM": "gemini_enterprise",
    "GOOGLE_CLOUD_PROJECT": project,
    "GOOGLE_CLOUD_LOCATION": location,
    "GEMINI_ENTERPRISE_COLLECTION_ID": collection,
    "PHOENIX_PROJECT_NAME": "aerobridge-ai",
}

if engine:
    updates["GEMINI_ENTERPRISE_ENGINE_ID"] = engine
if assistant:
    updates["GEMINI_ENTERPRISE_ASSISTANT_ID"] = assistant

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

echo "Gemini Enterprise API mode enabled in $ENV_FILE"
echo "Project: $PROJECT_ID"
echo "Location: $LOCATION"
echo "Collection: $COLLECTION_ID"
if [[ -z "$ENGINE_ID" || -z "$ASSISTANT_ID" ]]; then
  echo "Next: create/select a Gemini Enterprise engine + assistant and add:"
  echo "  GEMINI_ENTERPRISE_ENGINE_ID=..."
  echo "  GEMINI_ENTERPRISE_ASSISTANT_ID=..."
fi
