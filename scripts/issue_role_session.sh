#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
ROLE="${4:-${PARKPULSE_ROLE_SESSION_ROLE:-ops_team}}"
SUBJECT="${5:-${PARKPULSE_ROLE_SESSION_SUBJECT:-parkpulse-operator}}"
ISSUER_KEY_SECRET_NAME="${PARKPULSE_ROLE_ISSUER_KEY_SECRET:-parkpulse-role-issuer-key}"
APP_URL="${PARKPULSE_COMMAND_CENTER_URL:-http://127.0.0.1:3000}"
BROWSER_API_URL="${PARKPULSE_BROWSER_API_URL:-http://127.0.0.1:8001}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/issue_role_session.sh <gcp-project-id> [region] [service] [role] [subject]" >&2
  exit 2
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
GOOGLE_TOKEN="$(gcloud auth print-identity-token)"
ISSUER_KEY="$(gcloud secrets versions access latest --secret "$ISSUER_KEY_SECRET_NAME" --project "$PROJECT_ID")"
TMP_JSON="$(mktemp "${TMPDIR:-/tmp}/parkpulse-role-session.XXXXXX.json")"
trap 'rm -f "$TMP_JSON"' EXIT

curl -fsS \
  -X POST \
  -H "Authorization: Bearer ${GOOGLE_TOKEN}" \
  -H "x-parkpulse-role-issuer-key: ${ISSUER_KEY}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  "${SERVICE_URL}/api/park/auth/operator-session" \
  --data "{\"role\":\"${ROLE}\",\"subject\":\"${SUBJECT}\"}" > "$TMP_JSON"

python3 - "$TMP_JSON" "$APP_URL" "$BROWSER_API_URL" <<'PY'
import json
import sys
from urllib.parse import urlencode

payload = json.load(open(sys.argv[1]))
app_url = sys.argv[2]
browser_api_url = sys.argv[3]

if payload.get("status") != "issued" or not payload.get("token"):
    raise SystemExit(json.dumps(payload, indent=2))

query = urlencode({"api": browser_api_url, "roleToken": payload["token"]})
separator = "&" if "?" in app_url else "?"
safe_payload = {key: value for key, value in payload.items() if key != "token"}

print(json.dumps(safe_payload, indent=2))
print()
print("Open command center with signed role:")
print(f"{app_url}{separator}{query}")
print()
print("Use the token for API calls with header:")
print("x-parkpulse-role-token: <redacted>")
PY
