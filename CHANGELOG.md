# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

