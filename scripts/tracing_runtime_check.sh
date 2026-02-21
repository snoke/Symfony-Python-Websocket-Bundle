#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILES=${COMPOSE_FILES:-"docker-compose.yaml docker-compose.local.yaml"}
COMPOSE_ARGS=()
for file in $COMPOSE_FILES; do
  COMPOSE_ARGS+=("-f" "$file")
done

if ! docker compose "${COMPOSE_ARGS[@]}" ps >/dev/null 2>&1; then
  echo "docker compose not available or no config found."
  exit 1
fi

echo "Checking gateway OpenTelemetry runtime..."
if ! docker compose "${COMPOSE_ARGS[@]}" exec -T gateway python - <<'PY'
import opentelemetry.sdk
import opentelemetry.exporter.otlp.proto.http.trace_exporter
print("gateway otel ok")
PY
then
  echo "Gateway OTel check failed. Is the gateway container running?"
  exit 1
fi

echo "Checking symfony OpenTelemetry runtime..."
if ! docker compose "${COMPOSE_ARGS[@]}" exec -T symfony php -r "require '/app/vendor/autoload.php'; exit(class_exists('OpenTelemetry\\\\SDK\\\\Trace\\\\TracerProvider') ? 0 : 1);"; then
  echo "Symfony OTel check failed. Is the symfony container running?"
  exit 1
fi

echo "Tracing runtime check passed."
