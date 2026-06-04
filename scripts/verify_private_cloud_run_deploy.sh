#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
ROLE_AUTH_RESOURCE_NAME="${PARKPULSE_ROLE_AUTH_SECRET_NAME:-parkpulse-role-auth-secret}"
EXPECTED_REVISION="${PARKPULSE_EXPECTED_REVISION:-}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/verify_private_cloud_run_deploy.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/parkpulse-deploy-verify.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
GOOGLE_IDENTITY="$(gcloud auth print-identity-token)"

curl_json() {
  local method="$1"
  local path="$2"
  local output="$3"
  shift 3
  /usr/bin/curl -fsS --max-time 90 \
    -X "$method" \
    -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
    -H "Accept: application/json" \
    "$@" \
    "${SERVICE_URL}${path}" > "$output"
}

if [[ -n "$EXPECTED_REVISION" ]]; then
  echo "Verifying Cloud Run traffic targets ${EXPECTED_REVISION}..."
else
  echo "Verifying Cloud Run traffic targets latest ready revision..."
fi
gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format=json > "$TMP_DIR/service.json"
python3 - "$TMP_DIR/service.json" "$EXPECTED_REVISION" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
expected_revision = sys.argv[2].strip()
status = payload.get("status") or {}
spec = payload.get("spec") or {}
latest_ready = status.get("latestReadyRevisionName")
traffic = status.get("traffic") or []
spec_traffic = spec.get("traffic") or []
if not latest_ready:
    raise SystemExit("Cloud Run has no latest ready revision.")
if expected_revision:
    expected_status = [{"percent": 100, "revisionName": expected_revision}]
    expected_spec = [{"percent": 100, "revisionName": expected_revision}]
    if traffic != expected_status:
        raise SystemExit(f"Cloud Run traffic is not 100% expected revision: expected={expected_revision}, traffic={traffic}")
    if spec_traffic != expected_spec:
        raise SystemExit(f"Cloud Run spec is not pinned to expected revision: expected={expected_revision}, spec={spec_traffic}")
    print(f"Traffic: 100% {expected_revision}")
    raise SystemExit(0)
if traffic != [{"latestRevision": True, "percent": 100, "revisionName": latest_ready}]:
    raise SystemExit(f"Cloud Run traffic is not 100% latest ready revision: latest={latest_ready}, traffic={traffic}")
if spec_traffic != [{"latestRevision": True, "percent": 100}]:
    raise SystemExit(f"Cloud Run spec is not configured to track latest revision: {spec_traffic}")
print(f"Traffic: 100% latest ({latest_ready})")
PY

echo "Verifying readiness and MongoDB dependency..."
curl_json GET /readyz "$TMP_DIR/readyz.json"
python3 - "$TMP_DIR/readyz.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
issues = payload.get("readiness_issues") or []
mongo = ((payload.get("dependency_status") or {}).get("mongo") or {})
if payload.get("status") != "ok":
    raise SystemExit(f"/readyz is not ok: {payload.get('status')}")
if issues:
    raise SystemExit(f"/readyz has readiness issues: {issues}")
mongo_ready = mongo.get("connected") is True or (mongo.get("ready") is True and mongo.get("configured") is True)
if not mongo_ready:
    raise SystemExit(f"MongoDB is not connected in live readiness: {mongo}")
print("Readiness: ok; MongoDB configured for live runtime")
PY

echo "Verifying signed-role auth contract..."
ROLE_SIGNING_VALUE="$(gcloud secrets versions access latest --secret "$ROLE_AUTH_RESOURCE_NAME" --project "$PROJECT_ID")"
PYTHONPATH="backend" python3 - "$ROLE_SIGNING_VALUE" > "$TMP_DIR/signed-header.txt" <<'PY'
import sys

from park_role_access import sign_role_session

secret = sys.argv[1]
print(sign_role_session("post-deploy-verify", "ops_team", secret, issuer="parkpulse-private-cloud-run-verify"))
PY

SIGNED_ROLE_HEADER="$(cat "$TMP_DIR/signed-header.txt")"
curl_json GET /api/park/auth/status "$TMP_DIR/signed-auth-status.json" -H "x-parkpulse-role-token: ${SIGNED_ROLE_HEADER}"
python3 - "$TMP_DIR/signed-auth-status.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("mode") != "identity_readiness":
    raise SystemExit(f"Unexpected auth status payload: {payload}")
if payload.get("status") not in {"production_ready", "dev_signed_sessions"}:
    raise SystemExit(f"Role auth status is not accepted: {payload}")
if payload.get("signed_role_required") is not True:
    raise SystemExit("Signed role requirement is not enabled.")
print("Signed identity: authenticated; signed role required")
PY

echo "Verifying spoofed mutation remains blocked..."
spoof_code="$(/usr/bin/curl -sS --max-time 75 -o "$TMP_DIR/spoof.json" -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "x-parkpulse-role: ops_team" \
  "${SERVICE_URL}/api/park/operator-command" \
  --data '{"message":"dispatch crowd staff","execute":true}')"
if [[ "$spoof_code" != "401" && "$spoof_code" != "403" ]]; then
  echo "Expected spoofed role mutation to return 401/403, got ${spoof_code}" >&2
  cat "$TMP_DIR/spoof.json" >&2
  exit 1
fi
python3 - "$TMP_DIR/spoof.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
reason = ((payload.get("authorization") or {}).get("reason") or "")
normalized_reason = reason.lower()
if "role session" not in normalized_reason and "signed" not in normalized_reason:
    raise SystemExit(f"Spoofed mutation was not blocked for signed-role reason: {payload}")
print("Spoofed mutation: blocked")
PY

echo "Verifying role-authorization log records the denied mutation..."
curl_json GET '/api/park/role-authorization-log?limit=20' "$TMP_DIR/auth-log.json" -H "x-parkpulse-role-token: ${SIGNED_ROLE_HEADER}"
python3 - "$TMP_DIR/auth-log.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
denials = [
    row for row in rows
    if row.get("path") == "/api/park/operator-command" and row.get("allowed") is False
]
if payload.get("mode") != "role_authorization_log":
    raise SystemExit(f"Unexpected role authorization log payload: {payload}")
if not denials:
    raise SystemExit(f"Role authorization log lacks denied spoofed mutation: {payload}")
print(f"Role authorization log: {len(rows)} recent row(s), denied mutation recorded")
PY

echo "Private Cloud Run deploy verification passed."
