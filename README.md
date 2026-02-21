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

### Core stack details
What you get in `core` mode:
- Stateless gateway publishes events to broker(s)
- Symfony acts as producer/consumer (no webhook round‑trip)
- `symfony-consumer` service reads `ws.inbox` and updates `/api/ws/last-message`

Core flow (default):
1. Client → Gateway (WS message)
2. Gateway → Broker (`ws.inbox` stream / queue)
3. Symfony consumer → reads event → app logic

Optional: run consumer manually (if you don't use the service):
```
docker compose -f docker-compose.yaml -f docker-compose.local.yaml -f docker-compose.realtime-core.yaml exec -T symfony php bin/ws_inbox_consumer.php
```

Useful env vars in core:
- `WS_MODE=core`
- `EVENTS_MODE=broker|both|none`
- `WS_REDIS_DSN` / `WS_RABBITMQ_DSN`
- `WS_CONSUMER_LOG_LEVEL`

Verify core wiring quickly:
1. Start the WS client.
2. Send a demo message.
3. Check `/api/ws/last-message` (updated by the consumer).

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
ordering_key: room:123 (optional)
ordering_strategy: topic|subject (optional)
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
- `ORDERING_STRATEGY=none|topic|subject` (gateway)
- `ORDERING_TOPIC_FIELD` (gateway, default: `topic`)
- `ORDERING_SUBJECT_SOURCE=user|subject` (gateway)
- `ORDERING_PARTITION_MODE=none|suffix` (gateway)
- `ORDERING_PARTITION_MAX_LEN` (gateway)

---

## Ordering Strategy (core)
You can choose how ordering keys are derived for brokered events:
- `topic` strategy uses a message field (default `topic`, fallback to `type`).
- `subject` strategy uses the connection subject (default `user:{id}`) or explicit message `subject`.
- `none` disables ordering keys.

Partitioning (optional):
- If `ORDERING_PARTITION_MODE=suffix`, the gateway appends the ordering key to the broker stream/routing key.
- Example: `ws.inbox.room:123` (Redis stream or RabbitMQ routing key).

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

## Replay / Persistence Strategy
Status: implemented for Redis streams + RabbitMQ minimal + replay API hardening (branch `replay-strategy`).

Goal: define replay behavior for brokered events without hard-coding retention.

Strategies:
- `none`: no replay guarantees
- `bounded`: replay within a bounded window (stream maxlen / TTL)
- `durable`: external persistence for long-term replay

Policies:
- `REPLAY_RETENTION_SECONDS`
- `REPLAY_MAXLEN`
- `REPLAY_SNAPSHOT_SECONDS`

RabbitMQ minimal replay (durable + TTL/DLX):
- `RABBITMQ_QUEUE_TTL_MS`
- `RABBITMQ_INBOX_QUEUE`
- `RABBITMQ_INBOX_QUEUE_TTL_MS`
- `RABBITMQ_EVENTS_QUEUE`
- `RABBITMQ_EVENTS_QUEUE_TTL_MS`

RabbitMQ robust replay (API):
- `POST /internal/replay/rabbitmq` with `X-API-Key` header (or `{ api_key, limit }` payload)
- `RABBITMQ_REPLAY_TARGET_EXCHANGE`
- `RABBITMQ_REPLAY_TARGET_ROUTING_KEY`
- `RABBITMQ_REPLAY_MAX_BATCH`

Replay API hardening (defaults, configurable):
- API key required: `REPLAY_API_KEY` (fallback to `GATEWAY_API_KEY`)
- Rate limiting: `REPLAY_RATE_LIMIT_STRATEGY=in_memory|redis|none`
- Idempotency (optional): `REPLAY_IDEMPOTENCY_STRATEGY=none|in_memory|redis`
- Audit logging: `REPLAY_AUDIT_LOG=1`

Example request:
```
curl -X POST http://localhost:8180/internal/replay/rabbitmq \\
  -H "X-API-Key: $REPLAY_API_KEY" \\
  -H "Idempotency-Key: replay-2025-01-01" \\
  -H "Content-Type: application/json" \\
  -d '{"limit":100}'
```

RabbitMQ Policies (optional, infra-level):
```
rabbitmqctl set_policy ws-replay-ttl \"^ws\\\\.(inbox|events)$\" '{\"message-ttl\":600000,\"max-length\":100000,\"dead-letter-exchange\":\"ws.dlq\"}' --apply-to queues
rabbitmqctl set_policy ws-replay-lazy \"^ws\\\\.(inbox|events)$\" '{\"queue-mode\":\"lazy\"}' --apply-to queues
```

Monitoring / Alarms (suggested):
- Track DLQ depth + inbox/event queue depth.
- Alert on spikes in `rabbitmq_replay_total` or repeated replays.
- Observe replay API rate limits via `/metrics` counters.

---

## Presence Strategy
Status: gateway + Symfony interpretation + Symfony writer (branch `presence-strategy-ownership`).

Goal: make presence consistency configurable via strategy pattern and allow Symfony-specific interpretation.

Strategies:
- `ttl`: rely on Redis TTL + periodic refresh
- `heartbeat`: client heartbeats drive presence updates
- `session`: explicit connect/disconnect lifecycle only

Gateway policies:
- `PRESENCE_TTL_SECONDS`
- `PRESENCE_HEARTBEAT_SECONDS`
- `PRESENCE_GRACE_SECONDS`
- `PRESENCE_REFRESH_ON_MESSAGE`

Symfony interpretation policies:
- `WS_PRESENCE_INTERPRETATION_STRATEGY=none|ttl|heartbeat|session`
- `WS_PRESENCE_TTL_SECONDS`
- `WS_PRESENCE_HEARTBEAT_SECONDS`
- `WS_PRESENCE_GRACE_SECONDS`
- `WS_PRESENCE_USE_LAST_SEEN`

Symfony writer (ownership) policies:
- `WS_PRESENCE_WRITER_TYPE=none|redis`
- `WS_PRESENCE_WRITER_TTL_SECONDS`
- `WS_PRESENCE_WRITER_REFRESH_ON_MESSAGE`

Note: if Symfony owns presence, disable gateway presence updates to avoid double-writes.

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
