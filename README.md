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

## Notes
- This is a scaffold. For production, add Redis/RabbitMQ, persistence, and rate limits.
- For production, configure RS256 (JWKS or public key) in `gateway`.

## Bundle config (skeleton)
Supported types are declared but only `http` is implemented right now:
- `transport.type`: `http` | `redis_stream` | `rabbitmq`
- `presence.type`: `http` | `redis`
- `events.type`: `webhook` | `redis_stream` | `rabbitmq` | `none`
