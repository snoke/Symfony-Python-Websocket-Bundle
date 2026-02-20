# Realtime-Core (Broker-First)

Broker-first WebSocket stack:
- Gateway terminates WS + JWT, publishes all events via Redis/RabbitMQ.
- Presence lives in Redis (no HTTP roundtrip).
- Symfony is producer/consumer via broker.
- No webhook path in this branch.

Need webhook/HTTP presence? Switch to the `terminator` branch.

## Quick start (dev)
1. Generate dev keys (RS256):
   - `./scripts/gen_dev_keys.sh`
2. Build and run (broker-first):
   - `docker compose -f docker-compose.yaml -f docker-compose.local.yaml -f docker-compose.realtime-core.yaml up --build`
3. Open:
   - WebSocket: `ws://localhost:8180/ws`
   - API: `http://localhost:8180/api/ping`

## Minimal WS test client
This uses RS256 for local dev.

1. Install deps:
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r scripts/requirements.txt`
2. Run:
   - `JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws python scripts/ws_client.py`

To send a demo message on connect:
- `WS_SEND_MESSAGE=1 WS_MESSAGE_JSON='{"type":"chat","payload":"hello world"}' JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws python scripts/ws_client.py`

You should see `received: {"type":"pong"}`.

## Push demo (broker)
1. Start the WS client in one terminal.
2. Trigger a push from Symfony:
   - `./scripts/push_demo.sh`

The gateway consumes the outbox (Redis/Rabbit) and emits the event to the WS client.

## Why realtime-core
- Broker-first: events are streamed, not HTTP pushed.
- Gateway is mostly stateless (WS + presence in Redis).
- Scales to high connection counts (no Symfony boot per message).
- Symfony is producer/consumer, not the WS terminator.

## Broker event schema (gateway -> broker)
Events are published to Redis streams and/or RabbitMQ:
- Redis: `REDIS_INBOX_STREAM` (messages), `REDIS_EVENTS_STREAM` (connect/disconnect)
- RabbitMQ: `RABBITMQ_INBOX_EXCHANGE`, `RABBITMQ_EVENTS_EXCHANGE`

### Event types
- `connected`
- `disconnected`
- `message_received`

### Common fields
```
{
  "type": "connected|disconnected|message_received",
  "connection_id": "uuid",
  "user_id": "42",
  "subjects": ["user:42"],
  "connected_at": 1700000000
}
```

### message_received fields
```
{
  "message": { "type": "chat", "payload": "hello world" },
  "raw": "{\"type\":\"chat\",\"payload\":\"hello world\"}"
}
```

### Error / edge cases
- Invalid JWT: WS is closed with code `4401`.
- `ping` messages are answered with `pong` and **not** published.
- Non-JSON WS messages become `{"type":"raw","payload":"<text>"}` and are still forwarded.
- If rate limited, WS receives `{"type":"rate_limited"}`.

## Consume events in Symfony (worker required)
The gateway publishes connection/message events to:
- Redis stream `REDIS_EVENTS_STREAM` (default `ws.events`)
- RabbitMQ exchange `RABBITMQ_EVENTS_EXCHANGE` (default `ws.events`)

This branch does **not** ship a Symfony worker. Use your own Redis/Rabbit consumer and dispatch:
- `WebsocketConnectionEstablishedEvent`
- `WebsocketConnectionClosedEvent`
- `WebsocketMessageReceivedEvent`

Example listeners live in `symfony/src/EventListener`.

## Bundle config (broker-only)
```
snoke_ws:
  transport:
    type: redis_stream
    redis_stream:
      dsn: 'redis://redis:6379'
      stream: 'ws.outbox'
  presence:
    type: redis
    redis:
      dsn: 'redis://redis:6379'
      prefix: 'presence:'
  events:
    type: redis_stream
    redis_stream:
      dsn: 'redis://redis:6379'
      stream: 'ws.events'
```

## Quick start (prod compose)
1. Set env:
   - `cp .env.example .env` and edit
2. Create ACME storage:
   - `touch traefik/acme.json && chmod 600 traefik/acme.json`
3. Run:
   - `docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d --build`

## Security controls
Gateway JWT validation:
- `JWT_ISSUER` (optional)
- `JWT_AUDIENCE` (optional)
- `JWT_LEEWAY` (seconds, optional)

## Data sovereignty / GDPR (self-hosted)
- Connections, presence and events stay in **your** infrastructure.
- Retention is controlled via Redis TTL / broker retention.
- GDPR duties (erasure, access, purpose limitation) remain with you.

## Brokers (Redis/RabbitMQ)
RabbitMQ Management UI:
- `http://localhost:8167` (user/pass: `guest` / `guest`)
