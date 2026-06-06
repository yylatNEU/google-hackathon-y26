#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${PARKPULSE_RELEASE_SOURCE_DIR:-}}"

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/parkpulse-ops-agent-backend-release.XXXXXX")"
fi

if [[ -e "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "Release source directory is not empty: $OUTPUT_DIR" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"

BASE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
git -C "$ROOT_DIR" archive --format=tar HEAD backend scripts Makefile docs | tar -xf - -C "$OUTPUT_DIR"

PATCH_FILE="patches/ops-agent-copilot-hotpath-2026-06-05.patch"
(
  cd "$OUTPUT_DIR"
  git apply --check "${ROOT_DIR}/${PATCH_FILE}"
  git apply "${ROOT_DIR}/${PATCH_FILE}"
)

OVERLAY_FILES=(
  "backend/test_main_lightweight_copilot.py"
  "scripts/cloud_run_private_curl.sh"
  "scripts/deploy_private_cloud_run.sh"
  "scripts/verify_private_cloud_run_deploy.sh"
  "docs/ops-agent-conversation-release-2026-06-05.md"
  "$PATCH_FILE"
)

COPIED_FILES=()
for relative_path in "${OVERLAY_FILES[@]}"; do
  source_path="${ROOT_DIR}/${relative_path}"
  if [[ ! -e "$source_path" ]]; then
    continue
  fi
  mkdir -p "${OUTPUT_DIR}/$(dirname "$relative_path")"
  cp -p "$source_path" "${OUTPUT_DIR}/${relative_path}"
  COPIED_FILES+=("$relative_path")
done

mkdir -p "${OUTPUT_DIR}/output/release"
python3 - "$OUTPUT_DIR/output/release/ops-agent-backend-release-manifest.json" "$BASE_COMMIT" "$ROOT_DIR" "$PATCH_FILE" "${COPIED_FILES[@]}" <<'PY'
import datetime
import json
import sys

manifest_path = sys.argv[1]
base_commit = sys.argv[2]
source_root = sys.argv[3]
patch_file = sys.argv[4]
copied_files = sys.argv[5:]

payload = {
    "release": "ops-agent-conversation-backend",
    "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    "base_commit": base_commit,
    "source_root": source_root,
    "patch_file": patch_file,
    "overlay_files": copied_files,
    "deploy_command": "PARKPULSE_DEPLOY_NO_TRAFFIC=true scripts/deploy_private_cloud_run.sh <project> <region>",
    "traffic_shift_guard": "Set PARKPULSE_ALLOW_PRODUCTION_TRAFFIC_UPDATE=true only after no-traffic verification passes.",
}

with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

echo "Release source built: $OUTPUT_DIR"
echo "$OUTPUT_DIR"
