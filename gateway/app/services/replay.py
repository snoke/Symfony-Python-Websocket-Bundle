import uuid
import hashlib
from typing import Any, Dict

import aio_pika
from aio_pika import ExchangeType
from fastapi import HTTPException, Request

from .logging_service import LoggingService
from .metrics import MetricsService
from .rate_limit import (
    NullIdempotencyStore,
    RedisIdempotencyStore,
    InMemoryIdempotencyStore,
    RedisRateLimiter,
    InMemoryRateLimiter,
)
from .settings import Settings


class ReplayService:
    def __init__(
        self,
        settings: Settings,
        metrics: MetricsService,
        logger: LoggingService,
        rate_limiter: RedisRateLimiter | InMemoryRateLimiter,
        idempotency_store: NullIdempotencyStore | InMemoryIdempotencyStore | RedisIdempotencyStore,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._logger = logger
        self._rate_limiter = rate_limiter
        self._idempotency_store = idempotency_store

    def _audit(self, event: str, **fields: Any) -> None:
        if self._settings.REPLAY_AUDIT_LOG:
            self._logger.log(event, **fields)

    def _normalize_key(self, value: str) -> str:
        value = value.strip()
        if len(value) <= 128:
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _rate_limit_identity(self, api_key: str, caller_ip: str) -> str:
        if self._settings.REPLAY_RATE_LIMIT_KEY == "api_key":
            return api_key or caller_ip
        if self._settings.REPLAY_RATE_LIMIT_KEY == "ip":
            return caller_ip
        if self._settings.REPLAY_RATE_LIMIT_KEY == "api_key_and_ip":
            if api_key:
                return f"{api_key}:{caller_ip}"
            return caller_ip
        return api_key or caller_ip

    async def handle(self, payload: Dict[str, Any], request: Request):
        self._metrics.inc("replay_api_requests_total")
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        caller_ip = request.client.host if request.client else "unknown"
        api_key = (
            payload.get("api_key")
            or request.headers.get("X-API-Key")
            or request.headers.get("X-Api-Key")
            or ""
        )
        expected_key = self._settings.REPLAY_API_KEY or self._settings.GATEWAY_API_KEY

        if expected_key and api_key != expected_key:
            self._metrics.inc("replay_api_denied_total")
            self._audit("replay_api_denied", request_id=request_id, caller_ip=caller_ip)
            raise HTTPException(status_code=401, detail="invalid api key")
        if not self._settings.RABBITMQ_DSN:
            self._metrics.inc("replay_api_errors_total")
            self._audit("replay_api_error", request_id=request_id, caller_ip=caller_ip, error="rabbitmq not configured")
            raise HTTPException(status_code=500, detail="rabbitmq not configured")

        identity = self._normalize_key(self._rate_limit_identity(api_key, caller_ip) or caller_ip)
        if self._settings.REPLAY_RATE_LIMIT_STRATEGY != "none" and self._settings.REPLAY_RATE_LIMIT_PER_MINUTE > 0:
            allowed = await self._rate_limiter.allow(
                identity,
                self._settings.REPLAY_RATE_LIMIT_PER_MINUTE,
                self._settings.REPLAY_RATE_LIMIT_WINDOW_SECONDS,
            )
            if not allowed:
                self._metrics.inc("replay_api_rate_limited_total")
                self._audit(
                    "replay_api_rate_limited",
                    request_id=request_id,
                    caller_ip=caller_ip,
                    identity=identity,
                )
                raise HTTPException(status_code=429, detail="rate limit exceeded")

        idempotency_key = request.headers.get(self._settings.REPLAY_IDEMPOTENCY_HEADER, "") or payload.get(
            self._settings.REPLAY_IDEMPOTENCY_PAYLOAD_FIELD, ""
        )
        idempotency_key = self._normalize_key(idempotency_key) if idempotency_key else ""
        if idempotency_key:
            cached = await self._idempotency_store.get(idempotency_key)
            if cached is not None:
                self._metrics.inc("replay_api_idempotent_total")
                self._audit(
                    "replay_api_idempotent",
                    request_id=request_id,
                    caller_ip=caller_ip,
                    replayed=cached,
                )
                return {"replayed": cached, "idempotent": True}

        limit = int(payload.get("limit") or self._settings.RABBITMQ_REPLAY_MAX_BATCH)
        if limit <= 0:
            return {"replayed": 0}
        limit = min(limit, self._settings.RABBITMQ_REPLAY_MAX_BATCH)

        target_exchange = self._settings.RABBITMQ_REPLAY_TARGET_EXCHANGE or self._settings.RABBITMQ_INBOX_EXCHANGE
        target_routing_key = self._settings.RABBITMQ_REPLAY_TARGET_ROUTING_KEY or self._settings.RABBITMQ_INBOX_ROUTING_KEY

        replayed = 0
        try:
            connection = await aio_pika.connect_robust(self._settings.RABBITMQ_DSN)
            async with connection:
                channel = await connection.channel()
                dlq_exchange = await channel.declare_exchange(
                    self._settings.RABBITMQ_DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True
                )
                dlq_queue = await channel.declare_queue(self._settings.RABBITMQ_DLQ_QUEUE, durable=True)
                await dlq_queue.bind(dlq_exchange, routing_key=self._settings.RABBITMQ_DLQ_QUEUE)

                exchange = await channel.declare_exchange(target_exchange, ExchangeType.DIRECT, durable=True)

                while replayed < limit:
                    message = await dlq_queue.get(fail=False)
                    if message is None:
                        break
                    try:
                        await exchange.publish(
                            aio_pika.Message(
                                body=message.body,
                                headers={**(message.headers or {}), "replayed": True},
                            ),
                            routing_key=target_routing_key,
                        )
                        await message.ack()
                        replayed += 1
                    except Exception:
                        await message.nack(requeue=True)
                        break
        except Exception as exc:
            self._metrics.inc("replay_api_errors_total")
            self._audit("replay_api_error", request_id=request_id, caller_ip=caller_ip, error=str(exc))
            raise HTTPException(status_code=500, detail="replay failed") from exc

        if idempotency_key:
            await self._idempotency_store.set(idempotency_key, replayed, self._settings.REPLAY_IDEMPOTENCY_TTL_SECONDS)

        self._metrics.add("rabbitmq_replay_total", replayed)
        self._metrics.inc("replay_api_success_total")
        self._audit("replay_api_success", request_id=request_id, caller_ip=caller_ip, replayed=replayed, limit=limit)
        return {"replayed": replayed}
