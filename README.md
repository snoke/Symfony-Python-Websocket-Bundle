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
1. Build and run:
   - `docker compose up --build`
2. Open:
   - WebSocket: `ws://localhost/ws`
   - Symfony: `http://localhost/api/ping`

## Notes
- This is a scaffold. For production, add Redis/RabbitMQ, persistence, and rate limits.
