#!/usr/bin/env bash
set -euo pipefail

JWT_PRIVATE_KEY_FILE=${JWT_PRIVATE_KEY_FILE:-"./scripts/keys/dev_private.pem"}
WS_URL=${WS_URL:-"ws://localhost:8180/ws"}
DEMO_API_URL=${DEMO_API_URL:-"http://localhost:8180/api/ws/last-message"}
DEMO_API_KEY=${DEMO_API_KEY:-"dev-demo-key"}
TRACEPARENT=${TRACEPARENT:-"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
TRACE_ID=${TRACE_ID:-"4bf92f3577b34da6a3ce929d0e0e4736"}
COMPOSE_FILES=${COMPOSE_FILES:-"docker-compose.yaml docker-compose.local.yaml docker-compose.realtime-core.yaml"}

if [[ ! -f ".venv/bin/activate" ]]; then
  echo "Missing .venv. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r scripts/requirements.txt"
  exit 1
fi

echo "Ensure core stack is running with TRACING_STRATEGY=full and WS_TRACING_ENABLED=1 for span logs."

WS_MESSAGE_JSON=${WS_MESSAGE_JSON:-"{\"type\":\"chat\",\"payload\":\"hello world\",\"traceparent\":\"${TRACEPARENT}\",\"trace_id\":\"${TRACE_ID}\"}"}

source .venv/bin/activate

WS_SEND_MESSAGE=1 WS_MESSAGE_JSON="$WS_MESSAGE_JSON" JWT_PRIVATE_KEY_FILE="$JWT_PRIVATE_KEY_FILE" WS_URL="$WS_URL" \
  python scripts/ws_client.py >/tmp/ws_trace_smoke.log 2>&1 &
CLIENT_PID=$!

sleep 1

found=0
for i in {1..10}; do
  resp=$(curl -sS -H "X-Demo-Key: ${DEMO_API_KEY}" "$DEMO_API_URL" || true)
  if echo "$resp" | grep -q "$TRACEPARENT" && echo "$resp" | grep -q "$TRACE_ID"; then
    echo "Tracing propagation OK (traceparent + trace_id found in last-message)."
    found=1
    break
  fi
  sleep 1
done

kill "$CLIENT_PID" 2>/dev/null || true

if [[ $found -ne 1 ]]; then
  if command -v docker >/dev/null 2>&1; then
    COMPOSE_ARGS=()
    for file in $COMPOSE_FILES; do
      COMPOSE_ARGS+=("-f" "$file")
    done
    redis_out=$(docker compose "${COMPOSE_ARGS[@]}" exec -T redis redis-cli XREVRANGE ws.inbox + - COUNT 1 2>/dev/null || true)
    if echo "$redis_out" | grep -q "$TRACEPARENT" && echo "$redis_out" | grep -q "$TRACE_ID"; then
      echo "Tracing propagation OK (redis stream contains traceparent + trace_id)."
      exit 0
    fi
  fi
  echo "Tracing propagation failed. last-message did not contain traceparent/trace_id."
  echo "Response: $resp"
  exit 1
fi
