#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
DATASET="${BIGQUERY_DATASET:-parkpulse_analytics}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/validate_private_gcp_demo.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
TOKEN="$(gcloud auth print-identity-token)"
TMP_DIR="${TMPDIR:-/tmp}/parkpulse-private-validation"
mkdir -p "$TMP_DIR"

query_count() {
  local table="$1"
  bq query --nouse_legacy_sql --format=json \
    "SELECT COUNT(*) AS row_count FROM \`${PROJECT_ID}.${DATASET}.${table}\`" \
    2>/dev/null | python3 -c 'import json,sys; data=json.load(sys.stdin); print(int(data[0]["row_count"]) if data else 0)' \
    || printf '0'
}

echo "Checking Cloud Run private IAM..."
gcloud run services get-iam-policy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format=json > "$TMP_DIR/iam.json"
python3 - "$TMP_DIR/iam.json" <<'PY'
import json, sys
policy = json.load(open(sys.argv[1]))
members = [m for b in policy.get("bindings", []) for m in b.get("members", [])]
if "allUsers" in members or "allAuthenticatedUsers" in members:
    raise SystemExit("Cloud Run service is public; remove allUsers/allAuthenticatedUsers invoker bindings.")
print("IAM: private invoker policy confirmed")
PY

echo "Checking unauthenticated access is blocked..."
code="$(curl -sS -o /dev/null -w '%{http_code}' "${SERVICE_URL}/readyz" || true)"
if [[ "$code" != "403" ]]; then
  echo "Expected unauthenticated /readyz to return 403, got ${code}" >&2
  exit 1
fi
echo "Unauthenticated access: blocked with 403"

echo "Checking authenticated readiness..."
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${SERVICE_URL}/readyz" > "$TMP_DIR/ready.json"
cat "$TMP_DIR/ready.json"
echo

echo "Checking GCP integration status..."
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${SERVICE_URL}/api/gcp-gemini/status" > "$TMP_DIR/status.json"
python3 - "$TMP_DIR/status.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
checks = {
    "gemini": payload["gemini"]["ready"],
    "bigquery": payload["bigquery"]["ready"],
    "online_improvement": payload["online_improvement"]["ready"],
}
for name, ready in checks.items():
    if not ready:
        raise SystemExit(f"{name} is not ready")
print("GCP readiness:", checks)
PY

before_outcomes="$(query_count outcome_events)"
before_dispatches="$(query_count action_dispatches)"
before_evals="$(query_count eval_results)"

echo "Running one private Cloud Run agent scenario..."
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{"scenario_key":"ride_down"}' \
  "${SERVICE_URL}/api/park/agent-run" > "$TMP_DIR/agent-run.json"

python3 - "$TMP_DIR/agent-run.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
if payload.get("status") != "complete":
    raise SystemExit(f"Agent run did not complete: {payload.get('status')}")
analytics = payload.get("analytics", {})
if analytics.get("status") not in {"exported", "partial_error"}:
    raise SystemExit(f"Unexpected analytics export status: {analytics}")
if analytics.get("errors"):
    raise SystemExit(f"BigQuery export errors: {analytics['errors']}")
print("Agent run:", {
    "status": payload.get("status"),
    "scenario": payload.get("scenario_key"),
    "decision_id": payload.get("decision_id"),
    "outcome_id": payload.get("outcome_id"),
    "analytics": analytics.get("inserted", {}),
})
PY

sleep 3
after_outcomes="$(query_count outcome_events)"
after_dispatches="$(query_count action_dispatches)"
after_evals="$(query_count eval_results)"

python3 - <<PY
before = {
    "outcome_events": int("${before_outcomes}"),
    "action_dispatches": int("${before_dispatches}"),
    "eval_results": int("${before_evals}"),
}
after = {
    "outcome_events": int("${after_outcomes}"),
    "action_dispatches": int("${after_dispatches}"),
    "eval_results": int("${after_evals}"),
}
delta = {key: after[key] - before[key] for key in before}
if delta["outcome_events"] < 1 or delta["eval_results"] < 1:
    raise SystemExit(f"BigQuery row delta too small: before={before}, after={after}, delta={delta}")
print("BigQuery row delta:", delta)
PY

echo "Private GCP demo validation passed."
