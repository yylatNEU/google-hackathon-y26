#!/usr/bin/env bash
set -euo pipefail

screen -S parkpulse-backend-external -X quit >/dev/null 2>&1 || true
screen -S parkpulse-spring-external -X quit >/dev/null 2>&1 || true
screen -S parkpulse-frontend-external -X quit >/dev/null 2>&1 || true

for port in 8000 8010 5174; do
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -n "$pid" ]]; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
done
