# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-02-23
### Added
- MIT License file.
- Experimental Rust gateway with Docker Compose override (`docker-compose.rust-gateway.yaml`).
- Rust gateway services mirroring the Python gateway (WS, auth/JWT, rate limiting, metrics, Redis/Rabbit/Webhook handlers).
- Rust gateway tuning knobs: bounded WS outbox queue + optional Redis publish batching + JSON buffer pool sizing envs.
- Gateway smoke tests now include Redis outbox delivery check (core mode).
- Python gateway presence refresh tuning envs: `PRESENCE_REFRESH_ON_MESSAGE`, `PRESENCE_REFRESH_MIN_INTERVAL_SECONDS`, `PRESENCE_REFRESH_QUEUE_SIZE`.
- Gateway internal message envelope with optional Snowflake IDs (Python + Rust).
- Channel-based routing option (`CHANNEL_ROUTING_STRATEGY=channel_id`).
- Gateway role support (`GATEWAY_ROLE=read|write|both`) in Python + Rust.
- Python gateway WS outbox buffering with drop strategy (`WS_OUTBOX_QUEUE_SIZE`, `WS_OUTBOX_DROP_STRATEGY`).

### Changed
- Docs: clarify pre-release tagging for Composer and Docker (no stable/latest tags yet).
- Docs: simplify consumer setup steps now that the bundle is on Packagist.
- Docs: add gateway image quickstart to avoid repo clone.
- Docs: add ready-to-download gateway compose files for quickstart.
- Docs: remove smoke test instructions from README.
- Docs: move detailed core/terminator/test client/event schema to `dev.md`.
- Python gateway hot path optimizations (control-message fast path, pre-serialized event payloads for WS/broker/webhook).
- Presence updates now use Redis pipelines and a queued refresh worker to reduce load.
- Outbox consumer starts at latest when replay is disabled (`REPLAY_STRATEGY=none`).

## [0.1.1] - 2026-02-21
### Added
- Dev Docker builds now skip gRPC by default (build arg `INSTALL_GRPC=0`), while prod enables it.
- Symfony `bin/console` bootstrap for the minimal app.
- `symfony/console` dependency to support `ws:consume`.

### Changed
- Core consumer now reliably starts via `php bin/console ws:consume`.
- Chat demo now always echoes back to the sender (even if presence list is empty).

### Fixed
- `DemoTokenService` autowiring via explicit service alias in app config.

## [0.1.0] - 2026-02-21
### Added
- Chat demo (`/demo/chat`) available in both terminator and core modes.
- Core inbox consumer flow (Redis streams) with Symfony consumer service.
- RabbitMQ healthcheck in core compose for predictable startup.
- Optional demo push script documented in ops notes.

### Changed
- `docker-compose.local.yaml` renamed to `docker-compose.terminator.yaml`.
- Core startup uses compose-only toggles; terminator/core now selected by compose files.

### Fixed
- Redis stream publish argument order in bundle publisher.
- Redis presence scan cursor handling (avoid infinite scan loop).
- Gateway RabbitMQ connection now retries instead of failing startup.
