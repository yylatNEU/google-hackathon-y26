#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
ROLE_ISSUER_NAME="${PARKPULSE_ROLE_ISSUER_KEY_SECRET:-parkpulse-role-issuer-key}"

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
  /usr/bin/curl -fsS --max-time 20 \
    -X "$method" \
    -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
    -H "Accept: application/json" \
    "$@" \
    "${SERVICE_URL}${path}" > "$output"
}

echo "Verifying Cloud Run traffic targets latest ready revision..."
gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format=json > "$TMP_DIR/service.json"
python3 - "$TMP_DIR/service.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
status = payload.get("status") or {}
spec = payload.get("spec") or {}
latest_ready = status.get("latestReadyRevisionName")
traffic = status.get("traffic") or []
spec_traffic = spec.get("traffic") or []
if not latest_ready:
    raise SystemExit("Cloud Run has no latest ready revision.")
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
if mongo.get("connected") is not True or mongo.get("mode") != "mongodb":
    raise SystemExit(f"MongoDB is not connected in live readiness: {mongo}")
print("Readiness: ok; MongoDB connected")
PY

echo "Verifying signed-role auth contract..."
curl_json GET /api/park/auth/status "$TMP_DIR/auth-status.json"
python3 - "$TMP_DIR/auth-status.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("status") != "ready":
    raise SystemExit(f"Role auth status is not ready: {payload}")
if payload.get("trusted_issuer_enabled") is not True:
    raise SystemExit("Trusted role issuer is not enabled.")
if payload.get("signed_role_required") is not True:
    raise SystemExit("Signed role requirement is not enabled.")
print("Role auth: trusted issuer enabled; signed role required")
PY

echo "Verifying trusted issuer can mint a signed role session..."
ISSUER_HEADER="$(gcloud secrets versions access latest --secret "$ROLE_ISSUER_NAME" --project "$PROJECT_ID")"
/usr/bin/curl -fsS --max-time 20 \
  -X POST \
  -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
  -H "x-parkpulse-role-issuer-key: ${ISSUER_HEADER}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  "${SERVICE_URL}/api/park/auth/operator-session" \
  --data '{"role":"ops_team","subject":"post-deploy-verify"}' > "$TMP_DIR/session.json"
python3 - "$TMP_DIR/session.json" "$TMP_DIR/signed-header.txt" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("status") != "issued" or payload.get("role") != "ops_team" or not payload.get("token"):
    raise SystemExit(f"Trusted issuer did not issue an ops_team token: {payload}")
open(sys.argv[2], "w", encoding="utf-8").write(payload["token"])
print("Trusted issuer: issued ops_team signed session")
PY

SIGNED_ROLE_HEADER="$(cat "$TMP_DIR/signed-header.txt")"
curl_json GET /api/park/auth/status "$TMP_DIR/signed-auth-status.json" -H "x-parkpulse-role-token: ${SIGNED_ROLE_HEADER}"
python3 - "$TMP_DIR/signed-auth-status.json" <<'PY'
import json
import sys

identity = (json.load(open(sys.argv[1])).get("identity") or {})
if identity.get("authenticated") is not True or identity.get("auth_method") != "signed_role_session":
    raise SystemExit(f"Signed role token did not authenticate: {identity}")
print("Signed identity: authenticated")
PY

echo "Verifying spoofed mutation remains blocked..."
spoof_code="$(/usr/bin/curl -sS --max-time 20 -o "$TMP_DIR/spoof.json" -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "x-parkpulse-role: ops_team" \
  "${SERVICE_URL}/api/park/operator-command" \
  --data '{"message":"dispatch crowd staff","execute":true}')"
if [[ "$spoof_code" != "403" ]]; then
  echo "Expected spoofed role mutation to return 403, got ${spoof_code}" >&2
  cat "$TMP_DIR/spoof.json" >&2
  exit 1
fi
python3 - "$TMP_DIR/spoof.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
reason = ((payload.get("authorization") or {}).get("reason") or "")
if "Signed ParkPulse role session is required" not in reason:
    raise SystemExit(f"Spoofed mutation was not blocked for signed-role reason: {payload}")
print("Spoofed mutation: blocked")
PY

echo "Verifying role-access audit is Mongo-backed..."
curl_json GET /api/park/auth/audit "$TMP_DIR/audit.json"
python3 - "$TMP_DIR/audit.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
events = payload.get("events") or []
event_types = {event.get("event_type") for event in events}
if payload.get("storage") != "mongodb":
    raise SystemExit(f"Role access audit is not Mongo-backed: {payload}")
required = {"role_session_issued", "mutation_denied"}
if not required.issubset(event_types):
    raise SystemExit(f"Role access audit lacks expected events: required={required}, event_types={event_types}")
print(f"Audit: mongodb storage with {payload.get('event_count')} recent event(s)")
PY

echo "Private Cloud Run deploy verification passed."
