#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/runtime-common.sh"
parkpulse_prepare_runtime

cd "$RUNTIME_DIR"
exec "$NODE_BIN" ./node_modules/vite/bin/vite.js --host 0.0.0.0 "$@"
