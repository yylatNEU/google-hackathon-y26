#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
REQUEST_TIMEOUT_SECONDS="${PARKPULSE_AGENT_ROLE_REMOTE_VERIFY_TIMEOUT_SECONDS:-240}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/verify_private_cloud_run_agent_roles.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/parkpulse-agent-role-verify.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
GOOGLE_IDENTITY="$(gcloud auth print-identity-token)"

curl_json() {
  local method="$1"
  local path="$2"
  local output="$3"
  shift 3
  /usr/bin/curl --http1.1 -fsS --max-time "${REQUEST_TIMEOUT_SECONDS}" \
    -X "$method" \
    -H "Authorization: Bearer ${GOOGLE_IDENTITY}" \
    -H "Accept: application/json" \
    "$@" \
    "${SERVICE_URL}${path}" > "$output"
}

echo "Verifying deployed aggregate agent-role product readiness..."
curl_json GET '/api/park/agent-role-eval' "$TMP_DIR/agent-role-eval-real.json"
python3 - "$TMP_DIR/agent-role-eval-real.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
product = payload.get("product_readiness") if isinstance(payload.get("product_readiness"), dict) else {}
negative = payload.get("negative_fixtures") if isinstance(payload.get("negative_fixtures"), dict) else {}
adversarial = payload.get("adversarial_sampled") if isinstance(payload.get("adversarial_sampled"), dict) else {}
issues = []
if payload.get("status") != "passed":
    issues.append(f"real eval status={payload.get('status')}")
if int(payload.get("passed_role_count") or 0) < 5:
    issues.append(f"passed_role_count={payload.get('passed_role_count')}")
if product and (product.get("status") != "passed" or int(product.get("product_ready_role_count") or 0) < 5):
    issues.append(f"product_readiness={product}")
if negative and negative.get("status") != "passed":
    issues.append(f"negative_fixtures={negative}")
if adversarial and adversarial.get("status") != "passed":
    issues.append(f"adversarial_sampled={adversarial}")
if issues:
    raise SystemExit("Remote agent-role aggregate gate failed: " + "; ".join(issues))
print("Aggregate gate:", {
    "status": payload.get("status"),
    "average_score": payload.get("average_score"),
    "product_ready_roles": product.get("product_ready_role_count") if product else payload.get("passed_role_count"),
    "negative_status": negative.get("status"),
    "adversarial_status": adversarial.get("status"),
})
PY

write_role_body() {
  local role="$1"
  local output="$2"
  python3 - "$role" > "$output" <<'PY'
import json
import sys

role = sys.argv[1]
messages = {
    "scan": "Scan vague guest complaints and worker taps for early crowd risk before dispatching anything.",
    "react": "Food court is down and mobile orders are backing up near the west plaza; prepare a bounded response.",
    "proact": "Staff note: kids are crying near the barrier and the crowd stopped moving by the maze exit.",
    "customer": "Where should my family go next with low waits and a calm route?",
    "qa": "Pre-deploy failure mode matrix and production reliability go/no-go.",
}
print(json.dumps({"mode": role, "message": messages[role]}, separators=(",", ":"), sort_keys=True))
PY
}

validate_role_run() {
  local role="$1"
  local payload_file="$2"
  python3 - "$role" "$payload_file" <<'PY'
import json
import sys

role = sys.argv[1]
payload = json.load(open(sys.argv[2]))
work = payload.get("role_work_contract") if isinstance(payload.get("role_work_contract"), dict) else {}
trace = payload.get("digital_twin_tools") if isinstance(payload.get("digital_twin_tools"), dict) else {}
trace_eval = trace.get("deliberate_eval") if isinstance(trace.get("deliberate_eval"), dict) else {}
role_specific = work.get("role_specific_work") if isinstance(work.get("role_specific_work"), dict) else {}
telemetry = payload.get("run_telemetry") if isinstance(payload.get("run_telemetry"), dict) else {}
delivery = telemetry.get("delivery") if isinstance(telemetry.get("delivery"), dict) else payload.get("delivery", {})
delivery = delivery if isinstance(delivery, dict) else {}
summary = delivery.get("summary") if isinstance(delivery.get("summary"), dict) else {}
dispatch_count = int(summary.get("total") or payload.get("role_run", {}).get("dispatch_count") or 0)
selected = payload.get("selected_role") or payload.get("role_receipt", {}).get("role") or work.get("role")
called_tools = [str(tool) for tool in trace_eval.get("called_tools", [])] if isinstance(trace_eval.get("called_tools"), list) else []
tool_rationale = work.get("tool_rationale") if isinstance(work.get("tool_rationale"), list) else []

checks = {
    "selected_role_matches": selected == role,
    "trace_eval_passed": trace_eval.get("status") == "passed",
    "role_work_contract_role": work.get("role") == role,
    "has_role_description": bool(work.get("role_description")),
    "has_mission": bool(work.get("mission")),
    "has_boundary": bool(work.get("boundary")),
    "has_input_evidence": len(work.get("input_evidence") if isinstance(work.get("input_evidence"), list) else []) >= 2,
    "has_reasoning_steps": len(work.get("reasoning_steps") if isinstance(work.get("reasoning_steps"), list) else []) >= 4,
    "has_tool_rationale": len(tool_rationale) >= 2,
    "has_output_evidence": len(work.get("output_evidence") if isinstance(work.get("output_evidence"), list) else []) >= 2,
    "has_success_criteria": len(work.get("success_criteria") if isinstance(work.get("success_criteria"), list) else []) >= 2,
    "has_stop_conditions": len(work.get("escalation_or_stop_conditions") if isinstance(work.get("escalation_or_stop_conditions"), list) else []) >= 2,
}
if role in {"scan", "customer", "qa"}:
    checks["read_only_no_dispatch"] = dispatch_count == 0
if role in {"react", "proact"}:
    checks["receiver_dispatches_present"] = dispatch_count > 0
    checks["policy_evidence_present"] = trace_eval.get("policy_ok") is True and trace_eval.get("policy_evidence_ok") is True
    checks["dispatch_receipts_present"] = trace_eval.get("dispatch_receipts_ok") is True
if role == "scan":
    checks["scan_uncertainty_explained"] = bool(role_specific.get("uncertainty_disclosure"))
    checks["scan_next_role_condition"] = bool(role_specific.get("recommended_next_role_condition"))
if role == "react":
    checks["react_alternatives_considered"] = len(role_specific.get("alternatives_considered") if isinstance(role_specific.get("alternatives_considered"), list) else []) >= 2
    checks["react_rejected_actions_named"] = len(role_specific.get("rejected_actions") if isinstance(role_specific.get("rejected_actions"), list) else []) >= 1
    checks["react_receivers_named"] = len(role_specific.get("receiver_channels") if isinstance(role_specific.get("receiver_channels"), list) else []) >= 1
if role == "proact":
    checks["proact_baseline_compared"] = bool(role_specific.get("baseline_vs_action"))
    checks["proact_observed_response_used"] = bool(role_specific.get("observed_response"))
    checks["proact_learning_rule_present"] = bool(role_specific.get("learning_rule"))
if role == "customer":
    checks["customer_public_sources_named"] = len(role_specific.get("public_data_sources") if isinstance(role_specific.get("public_data_sources"), list) else []) >= 2
    checks["customer_privacy_boundary_named"] = bool(role_specific.get("privacy_boundary"))
    checks["customer_actions_bounded"] = len(role_specific.get("allowed_customer_actions") if isinstance(role_specific.get("allowed_customer_actions"), list) else []) >= 1
if role == "qa":
    checks["qa_failure_modes_named"] = len(role_specific.get("failure_modes_checked") if isinstance(role_specific.get("failure_modes_checked"), list) else []) >= 4
    checks["qa_observability_named"] = len(role_specific.get("observability_checks") if isinstance(role_specific.get("observability_checks"), list) else []) >= 3
    checks["qa_idempotency_named"] = bool(role_specific.get("idempotency_check"))

failed = [name for name, ok in checks.items() if ok is not True]
if failed:
    raise SystemExit(f"Remote {role} role run failed checks: {failed}")
print(f"{role} role:", {
    "dispatch_count": dispatch_count,
    "called_tools": len(called_tools),
    "input_evidence": len(work.get("input_evidence", [])),
    "reasoning_steps": len(work.get("reasoning_steps", [])),
    "tool_rationale": len(tool_rationale),
    "output_evidence": len(work.get("output_evidence", [])),
})
PY
}

for role in scan react proact customer qa; do
  echo "Verifying deployed ${role} role work contract..."
  write_role_body "$role" "$TMP_DIR/${role}-request.json"
  curl_json POST /api/park/agent-role-run "$TMP_DIR/${role}-run.json" \
    -H "Content-Type: application/json" \
    --data @"$TMP_DIR/${role}-request.json"
  validate_role_run "$role" "$TMP_DIR/${role}-run.json"
done

echo "Private Cloud Run agent-role product readiness verification passed."
