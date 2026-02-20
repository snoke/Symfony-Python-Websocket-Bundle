# Symfony + Python WebSocket Bundle Stack

This repo contains:
- `gateway/`: Python WebSocket gateway (FastAPI)
- `symfony/`: Symfony app + reusable bundle
- `traefik/`: Reverse proxy config

Default behavior:
- WebSocket connections terminate at the Python gateway.
- Symfony publishes push events to the gateway via HTTP.
- Presence is read from the gateway via HTTP.
- Events are delivered to Symfony via a webhook (enabled by default).

## Quick start (dev)
1. Generate dev keys (RS256):
   - `./scripts/gen_dev_keys.sh`
2. Build and run:
   - `docker compose -f docker-compose.yaml -f docker-compose.local.yaml up --build`
2. Open:
   - WebSocket: `ws://localhost:8180/ws`
   - Symfony: `http://localhost:8180/api/ping`

## Minimal WS test client
This uses RS256 for local dev.

1. Install deps:
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r scripts/requirements.txt`
2. Run:
   - `JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws python scripts/ws_client.py`

You should see `received: {"type":"pong"}`.

## Publisher demo (end-to-end)
1. Start the WS client in one terminal:
   - `JWT_PRIVATE_KEY_FILE=./scripts/keys/dev_private.pem WS_URL=ws://localhost:8180/ws python scripts/ws_client.py`
2. Trigger a push from Symfony in another terminal:
   - `./scripts/push_demo.sh`

You should see a JSON `event` on the WS client.

## Presence demo
- List all connections:
  - `curl -sS http://localhost:8180/api/online`
- List connections for a user:
  - `curl -sS "http://localhost:8180/api/online?user_id=42"`

## Brokers (Redis/RabbitMQ)
Start with brokers:
- `docker compose -f docker-compose.yaml -f docker-compose.local.yaml -f docker-compose.brokers.yaml up --build`

RabbitMQ Management UI:
- `http://localhost:8167` (user/pass: `guest` / `guest`)

## Using the bundle in another Symfony project
1. Copy `symfony/src/Snoke/WsBundle` into your project (or extract as a separate package later).
2. Add autoload:
```
"Snoke\\WsBundle\\": "src/Snoke/WsBundle/"
```
3. Register bundle in `config/bundles.php`:
```
Snoke\\WsBundle\\SnokeWsBundle::class => ['all' => true],
```
4. Add config (example):
```
vserver_ws:
  transport:
    type: http
    http:
      base_url: '%env(WS_GATEWAY_BASE_URL)%'
      publish_path: '/internal/publish'
      auth:
        type: api_key
        value: '%env(WS_GATEWAY_API_KEY)%'
  presence:
    type: http
    http:
      base_url: '%env(WS_GATEWAY_BASE_URL)%'
```

## Notes
- This is a scaffold. For production, add Redis/RabbitMQ, persistence, and rate limits.
- For production, configure RS256 (JWKS or public key) in `gateway`.

## Bundle config (skeleton)
Supported types are declared and now implemented for transport/presence:
- `transport.type`: `http` | `redis_stream` | `rabbitmq`
- `presence.type`: `http` | `redis`
- `events.type`: `webhook` | `redis_stream` | `rabbitmq` | `none`

### Redis transport (publisher)
Symfony config:
```
vserver_ws:
  transport:
    type: redis_stream
    redis_stream:
      dsn: 'redis://redis:6379'
      stream: 'ws.outbox'
```
Gateway env:
```
REDIS_DSN=redis://redis:6379
REDIS_STREAM=ws.outbox
```

### RabbitMQ transport (publisher)
Symfony config:
```
vserver_ws:
  transport:
    type: rabbitmq
    rabbitmq:
      dsn: 'amqp://guest:guest@rabbitmq:5672/'
      exchange: 'ws.outbox'
      queue: 'ws.outbox'
      routing_key: 'ws.outbox'
```
Gateway env:
```
RABBITMQ_DSN=amqp://guest:guest@rabbitmq:5672/
RABBITMQ_QUEUE=ws.outbox
```

### Redis presence
Symfony config:
```
vserver_ws:
  presence:
    type: redis
    redis:
      dsn: 'redis://redis:6379'
      prefix: 'presence:'
```
