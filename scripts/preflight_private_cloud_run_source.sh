#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_BUILD_ID="${PARKPULSE_EXPECTED_LAZY_ROUTER_BUILD_ID:-latency-hot-route-v5-2026-06-03}"
MAIN_FILE="${ROOT_DIR}/backend/main.py"
DEPLOY_FILE="${ROOT_DIR}/scripts/deploy_private_cloud_run.sh"
VERIFY_FILE="${ROOT_DIR}/scripts/verify_private_cloud_run_deploy.sh"
ROLLBACK_FILE="${ROOT_DIR}/scripts/rollback_private_cloud_run.sh"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Preflight failed: missing required file ${path#${ROOT_DIR}/}" >&2
    exit 1
  fi
}

require_text() {
  local path="$1"
  local pattern="$2"
  local label="$3"
  if ! grep -Fq "$pattern" "$path"; then
    echo "Preflight failed: ${label} not found in ${path#${ROOT_DIR}/}" >&2
    exit 1
  fi
}

require_file "$MAIN_FILE"
require_file "$DEPLOY_FILE"
require_file "$VERIFY_FILE"
require_file "$ROLLBACK_FILE"
require_file "${ROOT_DIR}/backend/park_role_access.py"
require_file "${ROOT_DIR}/backend/training_run_receipts.py"
require_file "${ROOT_DIR}/backend/controlled_training_generation.py"
require_file "${ROOT_DIR}/backend/controlled_training_eval.py"
require_file "${ROOT_DIR}/backend/review_label_pipeline.py"
require_file "${ROOT_DIR}/backend/training_readiness.py"

require_text "$MAIN_FILE" "LAZY_ROUTER_BUILD_ID = \"${EXPECTED_BUILD_ID}\"" "lazy router build marker ${EXPECTED_BUILD_ID}"
require_text "$MAIN_FILE" "path == \"/api/gcp-gemini/status\"" "lightweight GCP status hot route"
require_text "$MAIN_FILE" "path == \"/api/park/training-run-receipts\"" "training receipt route"
require_text "$MAIN_FILE" "path == \"/api/park/live-feed-events\"" "live-feed ingest route"
require_text "$MAIN_FILE" "path == \"/api/park/controlled-training-generation\"" "controlled training generation route"
require_text "$MAIN_FILE" "path == \"/api/park/controlled-training-eval\"" "controlled training eval route"
require_text "$MAIN_FILE" "path == \"/api/park/gcp-training-dry-run\"" "GCP training dry-run route"
require_text "$MAIN_FILE" "PARKPULSE_GCP_TRAINING_DRY_RUN_TIMEOUT_SECONDS" "bounded GCP training dry-run timeout"
require_text "${ROOT_DIR}/scripts/cloud_run_private_curl.sh" "x-parkpulse-role-token" "signed role curl helper"
require_text "${ROOT_DIR}/scripts/validate_private_gcp_demo.sh" "bounded_fallback" "validation bounded fallback acceptance"
require_text "$DEPLOY_FILE" "PARKPULSE_ROLE_SESSION_ISSUER_KEY" "trusted role issuer secret deploy binding"
require_text "$DEPLOY_FILE" "PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION" "strict signed-role mutation deploy env"
require_text "$DEPLOY_FILE" "PARKPULSE_LIVE_FEED_STORAGE=\${PARKPULSE_LIVE_FEED_STORAGE:-mongodb}" "MongoDB live-feed deploy default"
require_text "$DEPLOY_FILE" "scripts/verify_private_cloud_run_deploy.sh" "post-deploy verifier call"
require_text "$VERIFY_FILE" "sign_role_session" "signed role session live verification"
require_text "$VERIFY_FILE" "/api/park/role-authorization-log" "role authorization log live verification"
require_text "$ROLLBACK_FILE" "PARKPULSE_ROLE_SESSION_ISSUER_KEY" "rollback preflight trusted issuer guard"

PYTHONPATH="${ROOT_DIR}/backend" python3 -m py_compile \
  "${ROOT_DIR}/backend/main.py" \
  "${ROOT_DIR}/backend/park_role_access.py" \
  "${ROOT_DIR}/backend/training_run_receipts.py" \
  "${ROOT_DIR}/backend/controlled_training_generation.py" \
  "${ROOT_DIR}/backend/controlled_training_eval.py" \
  "${ROOT_DIR}/backend/review_label_pipeline.py" \
  "${ROOT_DIR}/backend/training_readiness.py"

PYTHONPATH="${ROOT_DIR}/backend" python3 - <<'PY'
import asyncio
import json

import main


async def call(path: str):
    sent = []
    scope = {"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await main.app(scope, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(body or b"{}")


async def main_check():
    status, payload = await call("/api/gcp-gemini/status")
    if status != 200:
        raise SystemExit(f"GCP status hot route returned {status}")
    if payload.get("build_id") != main.LAZY_ROUTER_BUILD_ID:
        raise SystemExit("GCP status hot route build marker mismatch")
    if payload.get("loads_full_runtime") is not False or payload.get("hot_path") is not True:
        raise SystemExit(f"GCP status route is not lightweight: {payload}")


asyncio.run(main_check())
PY

echo "Private Cloud Run source preflight passed: ${EXPECTED_BUILD_ID}"
