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
ROLE_AUTH_RESOURCE_NAME="${PARKPULSE_ROLE_AUTH_SECRET_NAME:-parkpulse-role-auth-secret}"
ROLE_SIGNING_VALUE="$(gcloud secrets versions access latest --secret "$ROLE_AUTH_RESOURCE_NAME" --project "$PROJECT_ID")"
mkdir -p "$TMP_DIR"

role_token() {
  local role="$1"
  PYTHONPATH="backend" python3 - "$ROLE_SIGNING_VALUE" "$role" <<'PY'
import sys

from park_role_access import sign_role_session

secret, role = sys.argv[1], sys.argv[2]
print(sign_role_session("cloud-run-validator", role, secret, issuer="parkpulse-private-validation"))
PY
}

OPS_ROLE_TOKEN="$(role_token ops_team)"
ML_ROLE_TOKEN="$(role_token ml_ops_admin)"

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

echo "Checking app-level ML role authorization..."
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ml_ops_admin" \
  -H "x-parkpulse-role-token: ${ML_ROLE_TOKEN}" \
  -H "Accept: application/json" \
  "${SERVICE_URL}/api/park/training-run-receipts?limit=1" > "$TMP_DIR/training-receipts.json"
python3 - "$TMP_DIR/training-receipts.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("mode") != "offline_training_run_receipt_ledger":
    raise SystemExit(f"ML role authorization check failed: {payload}")
if payload.get("labels_or_reward_changed") or payload.get("llm_used_for_reward_or_label"):
    raise SystemExit(f"Training receipt route violated learning boundary: {payload}")
print("ML role authorization: accepted")
PY

echo "Loading fresh validation live-feed events..."
python3 - <<'PY' > "$TMP_DIR/live-feed-events.json"
import json

events = [
    {
        "source": "weather",
        "source_event_id": "cloud-run-validation-weather",
        "entity_type": "park",
        "entity_id": "park",
        "signal_type": "weather_state",
        "value": {"heat_index_f": 78, "storm_risk": 0.05},
        "confidence": 0.92,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.weather",
    },
    {
        "source": "ride_ops",
        "source_event_id": "cloud-run-validation-ride",
        "entity_type": "ride",
        "entity_id": "coaster_alpha",
        "signal_type": "ride_status",
        "value": {"ride_id": "coaster_alpha", "status": "operational", "wait_mins": 24, "downtime_minutes": 0},
        "confidence": 0.91,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.ride_ops",
    },
    {
        "source": "guest_flow",
        "source_event_id": "cloud-run-validation-flow",
        "entity_type": "zone",
        "entity_id": "central_plaza",
        "signal_type": "zone_density",
        "value": {"zone_id": "central_plaza", "zone": "Central Plaza", "density": "moderate", "current_guests": 820},
        "confidence": 0.91,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.guest_flow",
    },
    {
        "source": "staffing",
        "source_event_id": "cloud-run-validation-staffing",
        "entity_type": "staffing",
        "entity_id": "park_staff",
        "signal_type": "coverage",
        "value": {"scheduled": 120, "checked_in": 113, "open_callouts": 2, "staff_ready_pct": 94, "coverage_status": "ready", "fatigue_risk_pct": 10},
        "confidence": 0.9,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.staffing",
    },
    {
        "source": "food_ops",
        "source_event_id": "cloud-run-validation-food",
        "entity_type": "food_location",
        "entity_id": "food_court_a",
        "signal_type": "inventory",
        "value": {
            "locations": [{"id": "food_court_a", "name": "Food Court A", "mobile_order_backlog": 8, "pickup_eta_minutes": 9, "low_inventory_items": []}],
            "top_backlog_location": {"id": "food_court_a", "mobile_order_backlog": 8},
            "top_eta_location": {"id": "food_court_a", "pickup_eta_minutes": 9},
            "low_inventory_items": [],
            "kitchen_load_pct": 24,
        },
        "confidence": 0.9,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.food_ops",
    },
    {
        "source": "operator_signal",
        "source_event_id": "cloud-run-validation-operator-signal",
        "entity_type": "guest_care",
        "entity_id": "park_guest_care",
        "signal_type": "guest_care_summary",
        "value": {"open_cases": 1, "complaint_rate_pct": 1.5, "top_drivers": ["wayfinding"], "recovery_queue": []},
        "confidence": 0.9,
        "freshness_seconds": 0,
        "raw_payload_ref": "cloud_run_validation.operator_signal",
    },
]
print(json.dumps({"events": events}, separators=(",", ":"), sort_keys=True))
PY
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ops_team" \
  -H "x-parkpulse-role-token: ${OPS_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d @"$TMP_DIR/live-feed-events.json" \
  "${SERVICE_URL}/api/park/live-feed-events" > "$TMP_DIR/live-feed-ingest.json"
python3 - "$TMP_DIR/live-feed-ingest.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
rows = payload.get("results", [])
bad = [row for row in rows if row.get("status") not in {"accepted", "accepted_with_warnings"}]
if bad:
    raise SystemExit(f"Live-feed event ingest failed: {bad[:2]}")
if len(rows) < 6:
    raise SystemExit(f"Expected six live-feed events, got {len(rows)}")
print("Live-feed events loaded:", {"count": len(rows), "sources": payload.get("sources")})
PY

echo "Generating controlled training pack and eval artifacts..."
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ml_ops_admin" \
  -H "x-parkpulse-role-token: ${ML_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{"minReviewLabels":1,"minOutcomeRows":3,"maxExamples":60,"writeArtifacts":true}' \
  "${SERVICE_URL}/api/park/controlled-training-generation" > "$TMP_DIR/controlled-training-generation.json"
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ml_ops_admin" \
  -H "x-parkpulse-role-token: ${ML_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$(python3 - "$TMP_DIR/controlled-training-generation.json" <<'PY'
import json
import sys

pack = json.load(open(sys.argv[1]))
print(json.dumps({"writeArtifact": True, "pack": pack}, separators=(",", ":"), sort_keys=True))
PY
)" \
  "${SERVICE_URL}/api/park/controlled-training-eval" > "$TMP_DIR/controlled-training-eval.json"
python3 - "$TMP_DIR/controlled-training-generation.json" "$TMP_DIR/controlled-training-eval.json" <<'PY'
import json
import sys

pack = json.load(open(sys.argv[1]))
eval_report = json.load(open(sys.argv[2]))
if pack.get("status") not in {"generated", "generated_with_blockers"}:
    raise SystemExit(f"Controlled training pack generation failed: {pack.get('readiness_issues') or pack}")
if eval_report.get("labels_or_reward_changed") or eval_report.get("llm_used_for_reward_or_label"):
    raise SystemExit(f"Controlled eval violated training boundary: {eval_report}")
print("Controlled training artifacts:", {
    "pack_id": pack.get("id"),
    "eval_id": eval_report.get("id"),
    "eval_status": eval_report.get("status"),
    "pack_status": pack.get("status"),
    "readiness_issues": pack.get("readiness_issues", [])[:4],
})
PY

echo "Checking BQML training dry run gate..."
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ml_ops_admin" \
  -H "x-parkpulse-role-token: ${ML_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$(python3 - "$TMP_DIR/controlled-training-eval.json" <<'PY'
import json
import sys

controlled_eval = json.load(open(sys.argv[1]))
print(json.dumps({"minRows": 3, "validateTables": True, "controlledEval": controlled_eval}, separators=(",", ":"), sort_keys=True))
PY
)" \
  "${SERVICE_URL}/api/park/gcp-training-dry-run" > "$TMP_DIR/gcp-training-dry-run.json"
python3 - "$TMP_DIR/gcp-training-dry-run.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("status") not in {"ready", "blocked"}:
    raise SystemExit(f"BQML dry run returned unexpected status: {payload}")
tables = payload.get("table_validation", {})
if tables.get("status") not in {"ready", "timeout"}:
    raise SystemExit(f"BigQuery table validation did not reach an accepted state: {tables}")
if payload.get("gcp_training_started") or payload.get("model_promotion_started"):
    raise SystemExit(f"Dry run mutated training state: {payload}")
print("BQML dry run:", {
    "would_start": payload.get("bqml_start", {}).get("would_start"),
    "model_id": payload.get("bqml_start", {}).get("model_id"),
    "table_validation": tables.get("status"),
    "status": payload.get("status"),
    "readiness_issues": payload.get("readiness_issues", [])[:6],
})
PY

before_outcomes="$(query_count outcome_events)"
before_dispatches="$(query_count action_dispatches)"
before_evals="$(query_count eval_results)"

echo "Running one private Cloud Run agent scenario..."
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ops_team" \
  -H "x-parkpulse-role-token: ${OPS_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{"scenario_key":"ride_down"}' \
  "${SERVICE_URL}/api/park/agent-run" > "$TMP_DIR/agent-run.json"

python3 - "$TMP_DIR/agent-run.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
if payload.get("status") not in {"complete", "bounded_fallback"}:
    raise SystemExit(f"Agent run did not reach an accepted production status: {payload.get('status')}")
analytics = payload.get("analytics", {})
if analytics.get("status") not in {"exported", "partial_error"}:
    raise SystemExit(f"Unexpected analytics export status: {analytics}")
if analytics.get("errors"):
    raise SystemExit(f"BigQuery export errors: {analytics['errors']}")
inserted = analytics.get("inserted", {}) if isinstance(analytics.get("inserted"), dict) else {}
if payload.get("status") == "bounded_fallback" and (inserted.get("outcome_events", 0) < 1 or inserted.get("eval_results", 0) < 1):
    raise SystemExit(f"Bounded fallback lacked BigQuery proof: {analytics}")
print("Agent run:", {
    "status": payload.get("status"),
    "scenario": payload.get("scenario_key"),
    "decision_id": payload.get("decision_id"),
    "outcome_id": payload.get("outcome_id"),
    "analytics": inserted,
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
