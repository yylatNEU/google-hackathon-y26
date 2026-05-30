#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/runtime-common.sh"
parkpulse_prepare_runtime

cd "$RUNTIME_DIR"
exec "$NPM_BIN" run lint:local -- "$@"
