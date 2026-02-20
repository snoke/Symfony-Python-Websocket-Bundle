#!/usr/bin/env bash
set -euo pipefail

JWT_PRIVATE_KEY_FILE="${JWT_PRIVATE_KEY_FILE:-./scripts/keys/dev_private.pem}"
WS_URL="${WS_URL:-ws://localhost:8180/ws}"
DEMO_API_URL="${DEMO_API_URL:-http://localhost:8180/api/ws/last-message}"
DEMO_API_KEY="${DEMO_API_KEY:-dev-demo-key}"
WS_MESSAGE_JSON="${WS_MESSAGE_JSON:-{\"type\":\"chat\",\"payload\":\"hello world\"}}"

source .venv/bin/activate

WS_SEND_MESSAGE=1 WS_MESSAGE_JSON="$WS_MESSAGE_JSON" JWT_PRIVATE_KEY_FILE="$JWT_PRIVATE_KEY_FILE" WS_URL="$WS_URL" \
  python scripts/ws_client.py &
CLIENT_PID=$!

sleep 1

curl -sS -H "X-Demo-Key: ${DEMO_API_KEY}" "$DEMO_API_URL" || true

kill "$CLIENT_PID" 2>/dev/null || true
