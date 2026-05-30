#!/usr/bin/env bash
set -euo pipefail

parkpulse_prepare_runtime() {
  SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  RUNTIME_DIR="${PARKPULSE_FRONTEND_RUNTIME_DIR:-/tmp/parkpulse_frontend_runtime}"
  NODE_BIN="${PARKPULSE_NODE_BIN:-/Users/yenyu/.local/bin/node}"
  NPM_BIN="${PARKPULSE_NPM_BIN:-/Users/yenyu/.local/bin/npm}"

  if [[ ! -x "$NODE_BIN" ]]; then
    NODE_BIN="$(command -v node)"
  fi
  if [[ ! -x "$NPM_BIN" ]]; then
    NPM_BIN="$(command -v npm)"
  fi
  export PATH="$(dirname "$NODE_BIN"):$PATH"

  mkdir -p "$RUNTIME_DIR"

  rsync -a --delete \
    --exclude '.git' \
    --exclude '.next' \
    --exclude '.next-dev' \
    --exclude '.next-build' \
    --exclude '.package-lock.hash' \
    --exclude 'node_modules' \
    "$SOURCE_DIR/" "$RUNTIME_DIR/"

  SOURCE_LOCK_HASH="$(shasum "$SOURCE_DIR/package-lock.json" | awk '{print $1}')"
  RUNTIME_LOCK_HASH_FILE="$RUNTIME_DIR/.package-lock.hash"
  RUNTIME_LOCK_HASH="$(cat "$RUNTIME_LOCK_HASH_FILE" 2>/dev/null || true)"

  if [[ ! -d "$RUNTIME_DIR/node_modules" \
    || ! -x "$RUNTIME_DIR/node_modules/.bin/vite" \
    || ! -x "$RUNTIME_DIR/node_modules/.bin/tsc" \
    || ! -d "$RUNTIME_DIR/node_modules/react" \
    || "$SOURCE_LOCK_HASH" != "$RUNTIME_LOCK_HASH" ]]; then
    (cd "$RUNTIME_DIR" && "$NPM_BIN" ci)
    printf '%s' "$SOURCE_LOCK_HASH" > "$RUNTIME_LOCK_HASH_FILE"
  fi
}
