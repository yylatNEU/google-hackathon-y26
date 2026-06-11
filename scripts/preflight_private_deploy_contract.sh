#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

require_file "$DEPLOY_FILE"
require_file "$VERIFY_FILE"
require_file "$ROLLBACK_FILE"

require_text "$DEPLOY_FILE" "PARKPULSE_ROLE_SESSION_ISSUER_KEY" "trusted role issuer secret deploy binding"
require_text "$DEPLOY_FILE" "PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION" "strict signed-role mutation deploy env"
require_text "$DEPLOY_FILE" "PARKPULSE_LIVE_FEED_STORAGE=\${PARKPULSE_LIVE_FEED_STORAGE:-mongodb}" "MongoDB live-feed deploy default"
require_text "$DEPLOY_FILE" "scripts/verify_private_cloud_run_deploy.sh" "post-deploy verifier call"
require_text "$VERIFY_FILE" "sign_role_session" "signed role session live verification"
require_text "$VERIFY_FILE" "/api/park/role-authorization-log" "role authorization log live verification"
require_text "$ROLLBACK_FILE" "PARKPULSE_ROLE_SESSION_ISSUER_KEY" "rollback preflight trusted issuer guard"

bash -n "$DEPLOY_FILE" "$VERIFY_FILE" "$ROLLBACK_FILE"

echo "Private deploy contract preflight passed."
