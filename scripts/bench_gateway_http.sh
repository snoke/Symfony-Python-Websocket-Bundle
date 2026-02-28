#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${BASE_URL:-http://host.docker.internal:8180}
VUS=${VUS:-50}
DURATION=${DURATION:-30s}
PUBLISH=${PUBLISH:-1}
API_KEY=${API_KEY:-dev-key}
K6_NETWORK=${K6_NETWORK:-}
NET_ARGS=""
if [ -n "$K6_NETWORK" ]; then
  NET_ARGS="--network ${K6_NETWORK}"
fi

docker run --rm -i \
  $NET_ARGS \
  -e BASE_URL="$BASE_URL" \
  -e VUS="$VUS" \
  -e DURATION="$DURATION" \
  -e PUBLISH="$PUBLISH" \
  -e API_KEY="$API_KEY" \
  -v "$PWD/scripts/bench_gateway_http.js:/script.js:ro" \
  grafana/k6 run /script.js
