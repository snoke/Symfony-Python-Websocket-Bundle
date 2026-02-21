# Symfony + Python Realtime Stack (Configurable)

This stack provides bidirectional, scalable Realtime for Symfony apps — without touching your Symfony core.

## Why this stack exists
- Mercure / SSE are server→client only — forcing client updates creates massive overhead
- Pusher / SaaS solutions are convenient, but your data, presence, security, and GDPR compliance are hosted externally
- High connection counts make booting full Symfony per WebSocket message inefficient
- The architecture allows true E2E encryption with full self-hosting control (keys never leave the clients). The gateway payload stays blind by design—unlike many PHP-centric WS stacks (e.g., Swoole) that couple transport and business logic in the same runtime

## What you get
- Incremental Symfony-first integration (`terminator`) — quick WebSocket + webhook setup; business logic stays fully in Symfony
- Broker-first high-scale architecture (`core`) — stateless gateway, Redis/RabbitMQ streaming; Symfony acts as producer/consumer
- Self-hosted data sovereignty — full control over connections, presence, retention, and GDPR obligations

In short: true WS, scalable, flexible, and Symfony-native. No magic SaaS lock-in.

---

## Modes (WS_MODE)
- `terminator` (default)  
  Symfony-first, Webhook + HTTP presence. Incremental, quick integration, ideal for moderate Realtime.
- `core`  
  Broker-first, stateless, Redis/RabbitMQ streaming. High-scale, Symfony is producer/consumer.

Event routing (EVENTS_MODE): `webhook | broker | both | none`

---

## Quick Start (terminator)
1. Generate dev keys (RS256):
   ```
   ./scripts/gen_dev_keys.sh
   ```
2. Build & run:
   ```
   docker compose -f docker-compose.yaml -f docker-compose.local.yaml up --build
   ```
3. Open / connect:
   - WebSocket: `ws://localhost:8180/ws`
   - API: `http://localhost:8180/api/ping`
4. Core inbox consumer:
   - `symfony-consumer` runs automatically in the core compose stack
   - it reads `ws.inbox` and updates `/api/ws/last-message`
4. Webhook enabled by default:
   ```
   SYMFONY_WEBHOOK_URL=http://symfony:8000/internal/ws/events
   ```

---

## Quick Start (core)
1. Generate dev keys (RS256):
   ```
   ./scripts/gen_dev_keys.sh
   ```
2. Build & run (broker-first):
   ```
   docker compose -f docker-compose.yaml -f docker-compose.local.yaml -f docker-compose.realtime-core.yaml up --build
   ```
3. Open / connect:
   - WebSocket: `ws://localhost:8180/ws`
   - API: `http://localhost:8180/api/ping`

---

## Minimal WS Test Client
1. Install dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```
2. Run client:
   ```
   JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws python scripts/ws_client.py
   ```
3. Send a demo message on connect:
   ```
   WS_SEND_MESSAGE=1 WS_MESSAGE_JSON='{"type":"chat","payload":"hello world"}' \
   JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws \
   python scripts/ws_client.py
   ```

Expected response: `{"type":"pong"}`

---

## Push Demo (terminator)
1. Start the WS client in one terminal.
2. Trigger a push from Symfony:
   ```
   ./scripts/push_demo.sh
   ```
The event appears on the WS client in real time.

For core mode:
```
WS_MODE=core ./scripts/push_demo.sh
```
This sends a WS message and checks `/api/ws/last-message`.

---

## Event Schema (gateway → webhook/broker)
Event types: `connected`, `disconnected`, `message_received`

Common fields:
```
type: connected|disconnected|message_received
connection_id: uuid
user_id: 42
subjects: ["user:42"]
connected_at: 1700000000
```

`message_received` extra fields:
```
message: { type: chat, payload: hello world }
raw: {"type":"chat","payload":"hello world"}
traceparent: 00-... (optional, W3C)
```

Edge cases:
- Invalid JWT → WS closed with `4401`
- `ping` messages → `pong` (not published)
- Non-JSON WS messages → `{"type":"raw","payload":""}`
- Rate-limited clients → `{"type":"rate_limited"}`

---

## Symfony Config Overview
Mode + transport/presence/events configurable in `symfony/config/packages/snoke_ws.yaml`

Key env vars:
- `WS_MODE=terminator|core`
- `EVENTS_MODE=webhook|broker|both|none`
- `LOG_LEVEL`, `LOG_FORMAT` (gateway)
- `WS_CONSUMER_LOG_LEVEL` (core consumer)
- `SYMFONY_WEBHOOK_URL` + `SYMFONY_WEBHOOK_SECRET` (terminator)
- `WS_GATEWAY_BASE_URL` + `WS_GATEWAY_API_KEY` (Symfony → gateway)
- `WS_REDIS_DSN`, `WS_RABBITMQ_DSN`, … (core/broker)

---

## Observability / Tracing Strategy
Status: OTel end-to-end tracing implemented (branch `tracing`).

Goal: real spans + propagation across Gateway → Broker → Symfony.
Includes producer/consumer spans for broker publish + outbox delivery.

Strategies:
- `none`: no tracing
- `propagate`: forward trace headers if present
- `full`: always create spans and propagate

Gateway policies:
- `TRACING_TRACE_ID_FIELD`
- `TRACING_HEADER_NAME`
- `TRACING_SAMPLE_RATE`
- `TRACING_EXPORTER=stdout|otlp|none`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`

Symfony policies:
- `WS_TRACING_ENABLED=0|1`
- `WS_TRACING_EXPORTER=stdout|otlp|none`
- `WS_TRACEPARENT_FIELD`
- `WS_TRACE_ID_FIELD`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_PROTOCOL`

### Tracing Smoke Checks (real)
1. Start the core stack (with realtime core enabled).
2. Runtime deps check (gateway + symfony):
   ```
   COMPOSE_FILES="docker-compose.yaml docker-compose.local.yaml docker-compose.realtime-core.yaml" \
     ./scripts/tracing_runtime_check.sh
   ```
3. End-to-end propagation check (traceparent + trace_id):
   ```
   ./scripts/tracing_e2e_check.sh
   ```

---

## Production Quickstart
1. Set env: `cp .env.example .env`
2. Create ACME storage:
   ```
   touch traefik/acme.json && chmod 600 traefik/acme.json
   ```
3. Run:
   ```
   docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d --build
   ```

---

## Security Controls
- Gateway JWT validation: `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_LEEWAY`
- Webhook signature: `SYMFONY_WEBHOOK_SECRET` (terminator)

---

## Data Sovereignty / GDPR
- Connections, presence, and events stay in your infrastructure
- Retention controlled via Redis TTL / broker retention
- GDPR duties (erasure, access, purpose limitation) remain with you

---

## Inbox Consumer (core)
The core stack includes a lightweight Redis stream consumer:
- Script: `symfony/bin/ws_inbox_consumer.php`
- Service: `App\Service\WsInboxConsumer`
- Purpose: reads `ws.inbox` and updates `/api/ws/last-message`

Run manually (optional):
```
docker compose -f docker-compose.yaml -f docker-compose.local.yaml -f docker-compose.realtime-core.yaml exec -T symfony php bin/ws_inbox_consumer.php
```

---

## Healthchecks
- Gateway: `GET /health`
- Symfony: `GET /api/ping`

---

## Brokers (Redis/RabbitMQ)
RabbitMQ Management UI: `http://localhost:8167` (user/pass: `guest` / `guest`)

---

## Old Branch Snapshots (archive)
- `git checkout terminator`
- `git checkout realtime-core`
