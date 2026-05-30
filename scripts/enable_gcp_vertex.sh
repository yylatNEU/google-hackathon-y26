#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
LOCATION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
ENV_FILE="backend/.env"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/enable_gcp_vertex.sh <gcp-project-id> [location]" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Install Google Cloud CLI first:" >&2
  echo "https://cloud.google.com/sdk/docs/install" >&2
  exit 127
fi

gcloud config set project "$PROJECT_ID"
gcloud services enable aiplatform.googleapis.com --project "$PROJECT_ID"

if [[ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ]]; then
  echo "No Application Default Credentials found. Starting ADC login..."
  gcloud auth application-default login
fi

python3 - "$ENV_FILE" "$PROJECT_ID" "$LOCATION" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
project = sys.argv[2]
location = sys.argv[3]

updates = {
    "GOOGLE_GENAI_USE_VERTEXAI": "true",
    "GOOGLE_CLOUD_PROJECT": project,
    "GOOGLE_CLOUD_LOCATION": location,
    "GOOGLE_GENAI_API_VERSION": "v1",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_MODEL_FALLBACKS": "gemini-2.0-flash",
    "PHOENIX_PROJECT_NAME": "aerobridge-ai",
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

echo "Vertex AI mode enabled in $ENV_FILE"
echo "Project: $PROJECT_ID"
echo "Location: $LOCATION"
