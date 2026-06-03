#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE="${3:-${PARKPULSE_CLOUD_RUN_SERVICE:-parkpulse-private-api}}"
TARGET_REVISION="${4:-${PARKPULSE_ROLLBACK_REVISION:-}}"
ROLLBACK_REASON="${PARKPULSE_ROLLBACK_REASON:-manual rollback}"
REPORT_DIR="${PARKPULSE_ROLLBACK_REPORT_DIR:-output/rollback}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: scripts/rollback_private_cloud_run.sh <gcp-project-id> [region] [service] [target-revision]" >&2
  exit 2
fi

mkdir -p "$REPORT_DIR"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/parkpulse-rollback.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format=json > "$TMP_DIR/service.json"

CURRENT_REVISION="$(python3 - "$TMP_DIR/service.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
traffic = (payload.get("status") or {}).get("traffic") or []
for row in traffic:
    if int(row.get("percent") or 0) == 100 and row.get("revisionName"):
        print(row["revisionName"])
        break
PY
)"

if [[ -z "$TARGET_REVISION" ]]; then
  gcloud run revisions list \
    --service "$SERVICE" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format=json > "$TMP_DIR/revisions.json"
  TARGET_REVISION="$(python3 - "$TMP_DIR/revisions.json" "$CURRENT_REVISION" <<'PY'
import json
import sys

current = sys.argv[2]
rows = json.load(open(sys.argv[1]))

def env_map(row):
    container = ((((row.get("spec") or {}).get("containers") or [{}])[0]) or {})
    return {item.get("name"): item for item in container.get("env") or []}

def env_value(env, name):
    return str((env.get(name) or {}).get("value") or "")

def has_secret(env, name):
    return bool(((env.get(name) or {}).get("valueFrom") or {}).get("secretKeyRef"))

def is_safe_rollback_target(row):
    conditions = (row.get("status") or {}).get("conditions") or []
    if not any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions):
        return False
    env = env_map(row)
    if env_value(env, "PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION").lower() != "true":
        return False
    if env_value(env, "PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN").lower() != "true":
        return False
    if env_value(env, "PARKPULSE_LIVE_FEED_STORAGE") != "mongodb":
        return False
    return all(has_secret(env, name) for name in ("PARKPULSE_ROLE_AUTH_SECRET", "PARKPULSE_ROLE_SESSION_ISSUER_KEY", "MONGODB_URI"))

for row in rows:
    name = (row.get("metadata") or {}).get("name")
    if name and name != current and is_safe_rollback_target(row):
        print(name)
        break
else:
    raise SystemExit("No previous ready revision passes rollback safety preflight.")
PY
)"
fi

if [[ -z "$CURRENT_REVISION" ]]; then
  echo "Unable to determine current 100% traffic revision." >&2
  exit 1
fi

if [[ "$TARGET_REVISION" == "$CURRENT_REVISION" ]]; then
  echo "Target revision is already serving 100% traffic: ${TARGET_REVISION}" >&2
  exit 1
fi

echo "Current revision: ${CURRENT_REVISION}"
echo "Target rollback revision: ${TARGET_REVISION}"

gcloud run revisions describe "$TARGET_REVISION" --project "$PROJECT_ID" --region "$REGION" --format=json > "$TMP_DIR/target-revision.json"
python3 - "$TMP_DIR/target-revision.json" "$TARGET_REVISION" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
target = sys.argv[2]
conditions = (payload.get("status") or {}).get("conditions") or []
if not any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions):
    raise SystemExit(f"Target revision is not ready: {target}")

container = (((payload.get("spec") or {}).get("containers") or [{}])[0]) or {}
env_rows = container.get("env") or []
env = {row.get("name"): row for row in env_rows}

def env_value(name: str) -> str:
    return str((env.get(name) or {}).get("value") or "")

def has_secret(name: str) -> bool:
    return bool(((env.get(name) or {}).get("valueFrom") or {}).get("secretKeyRef"))

required_truthy = {
    "PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION": env_value("PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION"),
    "PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN": env_value("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN"),
}
missing = [name for name, value in required_truthy.items() if value.lower() != "true"]
if missing:
    raise SystemExit(f"Target revision lacks strict signed-role env(s): {missing}")
for secret_env in ("PARKPULSE_ROLE_AUTH_SECRET", "PARKPULSE_ROLE_SESSION_ISSUER_KEY", "MONGODB_URI"):
    if not has_secret(secret_env):
        raise SystemExit(f"Target revision lacks required secret env: {secret_env}")
if env_value("PARKPULSE_LIVE_FEED_STORAGE") != "mongodb":
    raise SystemExit("Target revision does not use MongoDB live-feed storage.")
print("Target revision preflight: ready, strict role envs and required secrets present")
PY

echo "Promoting ${TARGET_REVISION} to 100% traffic..."
gcloud run services update-traffic "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --to-revisions "${TARGET_REVISION}=100" \
  --quiet

echo "Running rollback verifier..."
PARKPULSE_EXPECTED_REVISION="$TARGET_REVISION" scripts/verify_private_cloud_run_deploy.sh "$PROJECT_ID" "$REGION" "$SERVICE" | tee "$TMP_DIR/verify.log"

REPORT_PATH="${REPORT_DIR}/$(date +%Y%m%d-%H%M%S)-${SERVICE}-rollback.md"
{
  echo "# ParkPulse Private Cloud Run Rollback"
  echo
  echo "- Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- Project: ${PROJECT_ID}"
  echo "- Region: ${REGION}"
  echo "- Service: ${SERVICE}"
  echo "- Previous revision: ${CURRENT_REVISION}"
  echo "- Rolled back to: ${TARGET_REVISION}"
  echo "- Reason: ${ROLLBACK_REASON}"
  echo "- Verification: passed"
  echo
  echo "## Verifier Output"
  echo
  echo '```'
  cat "$TMP_DIR/verify.log"
  echo '```'
} > "$REPORT_PATH"

echo "Rollback complete."
echo "Report: ${REPORT_PATH}"
