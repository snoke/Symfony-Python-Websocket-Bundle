#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-http://localhost:8180}"
USER_ID="${USER_ID:-42}"
WS_MODE="${WS_MODE:-terminator}"

if [[ "$WS_MODE" == "core" ]]; then
  ./scripts/demo_message_flow.sh
else
  curl -sS -X POST "$HOST/api/push-demo/$USER_ID" | cat
fi
