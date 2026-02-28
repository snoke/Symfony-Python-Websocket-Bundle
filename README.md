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
   git clone https://github.com/snoke/Symfony-Realtime-Stack.git
   cd Symfony-Realtime-Stack
   ```
2. Install a gateway:
   ```
   # Python gateway
   git submodule update --init gateway/gateway-python
   ```
   ```
   # Rust gateway
   git submodule update --init gateway/gateway-rust
   ```
3. Generate dev keys (RS256):
   ```
   ./scripts/gen_dev_keys.sh
   ```
4. Start a mode (choose one) + pick a gateway (Python or Rust):

   Core mode (Python gateway):
   ```
   docker compose -f docker-compose.yaml -f docker-compose.realtime-core.yaml -f gateway/gateway-python/docker-compose.yaml up --build
   ```
   Terminator mode (Python gateway):
   ```
   docker compose -f docker-compose.yaml -f docker-compose.terminator.yaml -f gateway/gateway-python/docker-compose.yaml up --build
   ```
   Core mode (Rust gateway):
   ```
   docker compose -f docker-compose.yaml -f docker-compose.realtime-core.yaml -f gateway/gateway-rust/docker-compose.yaml up --build
   ```
   Terminator mode (Rust gateway):
   ```
   docker compose -f docker-compose.yaml -f docker-compose.terminator.yaml -f gateway/gateway-rust/docker-compose.yaml up --build
   ```

   Note: `docker-compose.yaml` only defines shared gateway settings; you must include one gateway compose file to supply the build.
   If Symfony runs outside Compose, override `SYMFONY_WEBHOOK_URL` to reach it (e.g. `http://host.docker.internal:8000/internal/ws/events`).
   Dev builds skip gRPC. If you need gRPC, either use `docker-compose.prod.yaml`
   or build with `INSTALL_GRPC=1`.
5. Verify:
   - Chat demo is live: `http://localhost:8180/demo/chat`
   - WebSocket: `ws://localhost:8180/ws`
   - API: `http://localhost:8180/api/ping`
