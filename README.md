# SymfonyRealtime Stack (Configurable)

This stack provides bidirectional, highly scalable realtime WebSocket for Symfony

## Why this stack exists
- Mercure / SSE are server→client only — forcing client updates creates massive overhead
- Pusher / SaaS solutions are convenient, but your data, presence, security, and GDPR compliance are hosted externally
- High connection counts make booting full Symfony per WebSocket message inefficient
- This architecture allows true E2E encryption with full self-hosting control (keys never leave the clients). The gateway payload stays blind by design — unlike many PHP-centric WS stacks (e.g., Swoole) that couple transport and business logic in the same runtime — while still keeping the integration Symfony-native.

## Modes & Routing
- `core` (broker-first): stateless gateway with Redis/RabbitMQ streaming; Symfony acts as producer/consumer
- `terminator` (Symfony-first): quick WebSocket + webhook setup; incremental integration

   Event routing (EVENTS_MODE): `webhook | broker | both | none`


## Quick Start
1. Clone this repo:
   ```
   git clone https://github.com/snoke/Symfony-Python-Realtime-Stack.git
   cd Symfony-Python-Realtime-Stack
   ```
   If you want the gateway source locally (submodules):
   ```
   git submodule update --init --recursive
   ```
2. Generate dev keys (RS256):
   ```
   ./scripts/gen_dev_keys.sh
   ```
3. Start a mode (choose one):

   Core mode:
   ```
   docker compose -f docker-compose.yaml -f docker-compose.realtime-core.yaml up --build
   ```
   Terminator mode:
   ```
   SYMFONY_WEBHOOK_URL=http://symfony:8000/internal/ws/events \
   docker compose -f docker-compose.yaml -f docker-compose.terminator.yaml up --build
   ```
   Dev builds skip gRPC. If you need gRPC, either use `docker-compose.prod.yaml`
   or build with `INSTALL_GRPC=1`.
4. Verify:
   - Chat demo is live: `http://localhost:8180/demo/chat`
   - WebSocket: `ws://localhost:8180/ws`
   - API: `http://localhost:8180/api/ping`


## Rust Gateway (experimental)
The Rust gateway can replace the Python gateway via a Compose override:

Terminator mode:
```
docker compose -f docker-compose.yaml -f docker-compose.terminator.yaml -f docker-compose.rust-gateway.yaml up --build
```

Core mode:
```
docker compose -f docker-compose.yaml -f docker-compose.realtime-core.yaml -f docker-compose.rust-gateway.yaml up --build
```

## Submodules (Gateways)
The gateways live in separate repos and are included as submodules:
- `gateway/gateway-python` (Python)
- `gateway/gateway-rust` (Rust)

Common flows:
```
# clone with both gateways
git clone --recurse-submodules https://github.com/snoke/Symfony-Python-Realtime-Stack.git

# only Python gateway
git submodule update --init gateway/gateway-python

# only Rust gateway
git submodule update --init gateway/gateway-rust

# update to latest commits
git submodule update --remote
```

## Project Integration
The Symfony bundle is published on Packagist (pre-release tags). The gateway is available as a Docker image. You only need to clone this repo if you want the full local stack with Traefik + Symfony + brokers.

### 1) Install the Symfony bundle (pre-release)
```
composer require snoke/ws-bundle:0.1.2 --ignore-platform-req=ext-grpc
```
If you actually need gRPC (e.g. OTEL gRPC exporter), install `ext-grpc` and run:
```
composer require snoke/ws-bundle:0.1.2
```

### 2) Run the gateway image
Create keys once:
```
mkdir -p ws-gateway/keys
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out ws-gateway/keys/dev_private.pem
openssl rsa -in ws-gateway/keys/dev_private.pem -pubout -out ws-gateway/keys/dev_public.pem
```

1. Core mode:
```
curl -fsSL https://raw.githubusercontent.com/snoke/Symfony-Python-Realtime-Stack/main/docker-compose.ws-gateway.core.yaml \
  -o ws-gateway/docker-compose.ws-gateway.core.yaml
cd ws-gateway
docker compose -f docker-compose.ws-gateway.core.yaml up
```
Then configure your Symfony app for core mode:
```
WS_MODE=core
WS_TRANSPORT_TYPE=redis_stream
WS_PRESENCE_TYPE=redis
WS_EVENTS_TYPE=redis_stream
WS_REDIS_DSN=redis://localhost:6379
WS_REDIS_STREAM=ws.outbox
WS_REDIS_EVENTS_STREAM=ws.events
WS_REDIS_PREFIX=presence:
WS_RABBITMQ_DSN=amqp://guest:guest@localhost:5672/
```
If Symfony runs in Docker, use `redis` and `rabbitmq` hostnames instead of `localhost`.

2. Terminator mode:
```
curl -fsSL https://raw.githubusercontent.com/snoke/Symfony-Python-Realtime-Stack/main/docker-compose.ws-gateway.terminator.yaml \
  -o ws-gateway/docker-compose.ws-gateway.terminator.yaml
cd ws-gateway
SYMFONY_WEBHOOK_URL=http://host.docker.internal:8000/internal/ws/events \
  docker compose -f docker-compose.ws-gateway.terminator.yaml up
```
On Linux, `host.docker.internal` may not resolve; use your host IP or add `--add-host=host.docker.internal:host-gateway`.
Then configure your Symfony app for terminator mode:
```
WS_MODE=terminator
WS_TRANSPORT_TYPE=http
WS_PRESENCE_TYPE=http
WS_EVENTS_TYPE=webhook
WS_GATEWAY_BASE_URL=http://localhost:8000
WS_GATEWAY_API_KEY=dev-key
```

## Development Notes
See `dev.md` for core/terminator details, test client usage, event schema, and ops notes.
