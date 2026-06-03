#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../spring-backend"

export PARKPULSE_SPRING_PORT="${PARKPULSE_SPRING_PORT:-8010}"
export PARKPULSE_RUNTIME_DIR="${PARKPULSE_RUNTIME_DIR:-/tmp/parkpulse}"

exec ./mvnw spring-boot:run
