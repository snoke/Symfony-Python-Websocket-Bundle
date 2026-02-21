# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- (nothing yet)

### Changed
- Docs: clarify pre-release tagging for Composer and Docker (no stable/latest tags yet).

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
