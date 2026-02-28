#!/usr/bin/env bash
set -euo pipefail

WS_URL=${WS_URL:-ws://host.docker.internal:8180/ws}
VUS=${VUS:-50}
DURATION=${DURATION:-30s}
JWT=${JWT:-}
PAYLOAD_BYTES=${PAYLOAD_BYTES:-}
MSG_COUNT=${MSG_COUNT:-}
SESSION_MS=${SESSION_MS:-}
K6_NETWORK=${K6_NETWORK:-}
NET_ARGS=""
if [ -n "$K6_NETWORK" ]; then
  NET_ARGS="--network ${K6_NETWORK}"
fi

if [ -z "$JWT" ]; then
  echo "JWT is required for WS benchmark. Example: JWT=... $0" >&2
  exit 1
fi

docker run --rm -i \
  $NET_ARGS \
  -e WS_URL="$WS_URL" \
  -e VUS="$VUS" \
  -e DURATION="$DURATION" \
  -e JWT="$JWT" \
  -e PAYLOAD_BYTES="$PAYLOAD_BYTES" \
  -e MSG_COUNT="$MSG_COUNT" \
  -e SESSION_MS="$SESSION_MS" \
  -v "$PWD/scripts/bench_gateway_ws.js:/script.js:ro" \
  grafana/k6 run /script.js
