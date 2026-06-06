#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
DATASET="${BIGQUERY_DATASET:-parkpulse_analytics}"
EXPECTED_BUILD_ID="${PARKPULSE_EXPECTED_LAZY_ROUTER_BUILD_ID:-latency-hot-route-v5-2026-06-03}"
ROLE_AUTH_RESOURCE_NAME="${PARKPULSE_ROLE_AUTH_SECRET_NAME:-parkpulse-role-auth-secret}"
VERIFY_URL="${PARKPULSE_PRIVATE_VERIFY_URL:-${PARKPULSE_CLOUD_RUN_URL:-}}"
READYZ_MAX_SECONDS="${PARKPULSE_SMOKE_READYZ_MAX_SECONDS:-20}"
READYZ_WARMUP_MAX_SECONDS="${PARKPULSE_SMOKE_READYZ_WARMUP_MAX_SECONDS:-150}"
READYZ_STABILIZE_ATTEMPTS="${PARKPULSE_SMOKE_READYZ_STABILIZE_ATTEMPTS:-6}"
GCP_STATUS_MAX_SECONDS="${PARKPULSE_SMOKE_GCP_STATUS_MAX_SECONDS:-10}"
GCP_STATUS_WARMUP_MAX_SECONDS="${PARKPULSE_SMOKE_GCP_STATUS_WARMUP_MAX_SECONDS:-150}"
GCP_STATUS_STABILIZE_ATTEMPTS="${PARKPULSE_SMOKE_GCP_STATUS_STABILIZE_ATTEMPTS:-6}"
ML_RECEIPT_MAX_SECONDS="${PARKPULSE_SMOKE_ML_RECEIPT_MAX_SECONDS:-45}"
ML_RECEIPT_WARMUP_MAX_SECONDS="${PARKPULSE_SMOKE_ML_RECEIPT_WARMUP_MAX_SECONDS:-150}"
ML_RECEIPT_STABILIZE_ATTEMPTS="${PARKPULSE_SMOKE_ML_RECEIPT_STABILIZE_ATTEMPTS:-4}"
AGENT_RUN_MAX_SECONDS="${PARKPULSE_SMOKE_AGENT_RUN_MAX_SECONDS:-90}"
TMP_DIR="${TMPDIR:-/tmp}/parkpulse-private-smoke"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/smoke_private_cloud_run_production.sh <gcp-project-id> [region] [service]" >&2
  exit 2
fi

mkdir -p "$TMP_DIR"
SERVICE_URL="$VERIFY_URL"
if [[ -z "$SERVICE_URL" ]]; then
  SERVICE_URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
fi
TOKEN="$(gcloud auth print-identity-token)"
ROLE_SIGNING_VALUE="$(gcloud secrets versions access latest --secret "$ROLE_AUTH_RESOURCE_NAME" --project "$PROJECT_ID")"

role_token() {
  local role="$1"
  PYTHONPATH="backend" python3 - "$ROLE_SIGNING_VALUE" "$role" <<'PY'
import sys

from park_role_access import sign_role_session

secret, role = sys.argv[1], sys.argv[2]
print(sign_role_session("cloud-run-smoke", role, secret, issuer="parkpulse-private-smoke"))
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

timed_curl() {
  local label="$1"
  local max_seconds="$2"
  local output="$3"
  shift 3
  local elapsed
  elapsed="$(curl -fsS -w '%{time_total}' -o "$output" "$@")"
  python3 - "$label" "$elapsed" "$max_seconds" <<'PY'
import sys

label, elapsed, max_seconds = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
print(f"{label}: {elapsed:.3f}s")
if elapsed > max_seconds:
    raise SystemExit(f"{label} exceeded latency threshold {max_seconds:g}s: {elapsed:.3f}s")
PY
}

echo "Checking service revision..."
gcloud run services describe "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.latestReadyRevisionName,status.traffic[0].revisionName,status.traffic[0].percent)'

echo "Stabilizing readiness hot path..."
fast_readyz_count=0
for attempt in $(seq 1 "$READYZ_STABILIZE_ATTEMPTS"); do
  elapsed="$(curl -fsS -w '%{time_total}' -o "$TMP_DIR/readyz.json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/json" \
    "${SERVICE_URL}/readyz")"
  python3 - "$attempt" "$elapsed" "$READYZ_MAX_SECONDS" "$READYZ_WARMUP_MAX_SECONDS" <<'PY'
import sys

attempt, elapsed, max_seconds, warmup_max = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
label = "fast" if elapsed <= max_seconds else "warming"
print(f"readyz attempt {attempt}: {elapsed:.3f}s ({label})")
if elapsed > warmup_max:
    raise SystemExit(f"readyz attempt {attempt} exceeded warmup budget {warmup_max:g}s: {elapsed:.3f}s")
PY
  if python3 - "$elapsed" "$READYZ_MAX_SECONDS" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
  then
    fast_readyz_count=$((fast_readyz_count + 1))
  else
    fast_readyz_count=0
  fi
  if [[ "$fast_readyz_count" -ge 2 ]]; then
    break
  fi
done
if [[ "$fast_readyz_count" -lt 2 ]]; then
  echo "readyz did not stabilize to two consecutive responses under ${READYZ_MAX_SECONDS}s after ${READYZ_STABILIZE_ATTEMPTS} attempts" >&2
  exit 1
fi
python3 - "$TMP_DIR/readyz.json" "$EXPECTED_BUILD_ID" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
expected = sys.argv[2]
if payload.get("build_id") != expected:
    raise SystemExit(f"Unexpected build_id: {payload.get('build_id')} expected {expected}")
if payload.get("status") not in {"ok", "degraded"}:
    raise SystemExit(f"Readiness status is not acceptable: {payload.get('status')}")
if payload.get("mode") not in {"readyz_fast", "readyz_timeout_fallback", None}:
    raise SystemExit(f"Readiness is not on the lazy readiness contract: {payload.get('mode')}")
deps = payload.get("dependency_status") or payload.get("configured_dependencies") or {}
for name in ("gemini", "bigquery"):
    value = deps.get(name)
    if isinstance(value, dict):
        ready = bool(value.get("ready")) if "ready" in value else bool(value.get("configured"))
    else:
        ready = bool(value)
    if not ready:
        raise SystemExit(f"{name} is not ready: {deps.get(name)}")
print("readyz proof:", {"build_id": payload.get("build_id"), "status": payload.get("status"), "mode": payload.get("mode"), "full_app_loaded": payload.get("full_app_loaded")})
PY

echo "Checking GCP status hot path..."
fast_gcp_count=0
for attempt in $(seq 1 "$GCP_STATUS_STABILIZE_ATTEMPTS"); do
  elapsed="$(curl -fsS -w '%{time_total}' -o "$TMP_DIR/gcp-status.json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/json" \
    "${SERVICE_URL}/api/gcp-gemini/status")"
  python3 - "$attempt" "$elapsed" "$GCP_STATUS_MAX_SECONDS" "$GCP_STATUS_WARMUP_MAX_SECONDS" <<'PY'
import sys

attempt, elapsed, max_seconds, warmup_max = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
label = "fast" if elapsed <= max_seconds else "warming"
print(f"gcp_status attempt {attempt}: {elapsed:.3f}s ({label})")
if elapsed > warmup_max:
    raise SystemExit(f"gcp_status attempt {attempt} exceeded warmup budget {warmup_max:g}s: {elapsed:.3f}s")
PY
  if python3 - "$elapsed" "$GCP_STATUS_MAX_SECONDS" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
  then
    fast_gcp_count=$((fast_gcp_count + 1))
  else
    fast_gcp_count=0
  fi
  if [[ "$fast_gcp_count" -ge 2 ]]; then
    break
  fi
done
if [[ "$fast_gcp_count" -lt 2 ]]; then
  echo "gcp_status did not stabilize to two consecutive responses under ${GCP_STATUS_MAX_SECONDS}s after ${GCP_STATUS_STABILIZE_ATTEMPTS} attempts" >&2
  exit 1
fi
python3 - "$TMP_DIR/gcp-status.json" "$EXPECTED_BUILD_ID" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
expected = sys.argv[2]
if payload.get("build_id") != expected:
    raise SystemExit(f"GCP status build_id mismatch: {payload.get('build_id')}")
if payload.get("hot_path") is not True or payload.get("loads_full_runtime") is not False:
    raise SystemExit(f"GCP status is not the lightweight hot path: {payload}")
for name in ("gemini", "bigquery", "online_improvement"):
    if not payload.get(name, {}).get("ready"):
        raise SystemExit(f"{name} is not ready: {payload.get(name)}")
print("gcp status proof:", {"hot_path": payload.get("hot_path"), "loads_full_runtime": payload.get("loads_full_runtime")})
PY

echo "Checking signed ML receipt route..."
fast_receipt_count=0
for attempt in $(seq 1 "$ML_RECEIPT_STABILIZE_ATTEMPTS"); do
  elapsed="$(curl -fsS -w '%{time_total}' -o "$TMP_DIR/training-receipts.json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-parkpulse-role: ml_ops_admin" \
    -H "x-parkpulse-role-token: ${ML_ROLE_TOKEN}" \
    -H "Accept: application/json" \
    "${SERVICE_URL}/api/park/training-run-receipts?limit=1")"
  python3 - "$attempt" "$elapsed" "$ML_RECEIPT_MAX_SECONDS" "$ML_RECEIPT_WARMUP_MAX_SECONDS" <<'PY'
import sys

attempt, elapsed, max_seconds, warmup_max = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
label = "fast" if elapsed <= max_seconds else "warming"
print(f"ml_receipts attempt {attempt}: {elapsed:.3f}s ({label})")
if elapsed > warmup_max:
    raise SystemExit(f"ml_receipts attempt {attempt} exceeded warmup budget {warmup_max:g}s: {elapsed:.3f}s")
PY
  if python3 - "$elapsed" "$ML_RECEIPT_MAX_SECONDS" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
  then
    fast_receipt_count=$((fast_receipt_count + 1))
  else
    fast_receipt_count=0
  fi
  if [[ "$fast_receipt_count" -ge 1 ]]; then
    break
  fi
done
if [[ "$fast_receipt_count" -lt 1 ]]; then
  echo "ml_receipts did not stabilize under ${ML_RECEIPT_MAX_SECONDS}s after ${ML_RECEIPT_STABILIZE_ATTEMPTS} attempts" >&2
  exit 1
fi
python3 - "$TMP_DIR/training-receipts.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("mode") != "offline_training_run_receipt_ledger":
    raise SystemExit(f"Unexpected receipt payload: {payload}")
if payload.get("labels_or_reward_changed") or payload.get("llm_used_for_reward_or_label"):
    raise SystemExit(f"Receipt route violated learning boundary: {payload}")
print("receipt proof:", {"status": payload.get("status"), "mode": payload.get("mode")})
PY

before_outcomes="$(query_count outcome_events)"
before_dispatches="$(query_count action_dispatches)"
before_evals="$(query_count eval_results)"

echo "Checking signed ops agent run and BigQuery row delta..."
timed_curl agent_run "$AGENT_RUN_MAX_SECONDS" "$TMP_DIR/agent-run.json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-parkpulse-role: ops_team" \
  -H "x-parkpulse-role-token: ${OPS_ROLE_TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{"scenario_key":"ride_down"}' \
  "${SERVICE_URL}/api/park/agent-run"
python3 - "$TMP_DIR/agent-run.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("status") not in {"complete", "bounded_fallback"}:
    raise SystemExit(f"Unexpected agent status: {payload.get('status')}")
analytics = payload.get("analytics", {})
inserted = analytics.get("inserted", {}) if isinstance(analytics.get("inserted"), dict) else {}
if analytics.get("status") not in {"exported", "partial_error"} or analytics.get("errors"):
    raise SystemExit(f"Agent analytics proof failed: {analytics}")
if inserted.get("outcome_events", 0) < 1 or inserted.get("eval_results", 0) < 1:
    raise SystemExit(f"Agent run did not export required proof rows: {analytics}")
print("agent proof:", {"status": payload.get("status"), "decision_id": payload.get("decision_id"), "outcome_id": payload.get("outcome_id"), "inserted": inserted})
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

echo "Private Cloud Run production smoke passed."
