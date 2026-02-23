import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import aio_pika
import redis.asyncio as redis
from aio_pika import ExchangeType
from opentelemetry.trace import SpanKind

from .logging_service import LoggingService
from .message import internal_from_dict
from .metrics import MetricsService
from .settings import Settings
from .tracing import TracingService


class BrokerService:
    def __init__(
        self,
        settings: Settings,
        metrics: MetricsService,
        tracing: TracingService,
        logger: LoggingService,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._tracing = tracing
        self._logger = logger
        self.redis_publish_client: Optional[redis.Redis] = None
        self.rabbit_publish_connection: Optional[aio_pika.RobustConnection] = None
        self.rabbit_publish_channel: Optional[aio_pika.Channel] = None
        self.rabbit_inbox_exchange: Optional[aio_pika.Exchange] = None
        self.rabbit_events_exchange: Optional[aio_pika.Exchange] = None
        self._last_stream_trim: Dict[str, float] = {}
        self._send_to_subjects: Optional[Callable[[list, Any], Awaitable[int]]] = None

    def set_sender(self, sender: Callable[[list, Any], Awaitable[int]]) -> None:
        self._send_to_subjects = sender

    def _strip_internal_payload(self, payload: Any) -> Any:
        if not self._settings.OUTBOX_STRIP_INTERNAL:
            return payload
        if not isinstance(payload, dict):
            return payload
        internal = internal_from_dict(payload)
        if not internal:
            return payload
        return internal.to_client_payload()

    async def startup(self) -> None:
        if self._settings.REDIS_DSN:
            self.redis_publish_client = redis.from_url(self._settings.REDIS_DSN, decode_responses=True)
            if self._settings.ROLE_READ:
                asyncio.create_task(self._redis_outbox_consumer())
        if self._settings.RABBITMQ_DSN:
            asyncio.create_task(self._init_rabbitmq())
            if self._settings.ROLE_READ:
                asyncio.create_task(self._rabbit_outbox_consumer())

    async def shutdown(self) -> None:
        if self.rabbit_publish_connection:
            await self.rabbit_publish_connection.close()
            self.rabbit_publish_connection = None

    def _rabbit_queue_args(self, ttl_ms: int) -> Dict[str, Any]:
        args: Dict[str, Any] = {}
        if ttl_ms > 0:
            args["x-message-ttl"] = ttl_ms
        if self._settings.RABBITMQ_DLQ_EXCHANGE:
            args["x-dead-letter-exchange"] = self._settings.RABBITMQ_DLQ_EXCHANGE
            if self._settings.RABBITMQ_DLQ_QUEUE:
                args["x-dead-letter-routing-key"] = self._settings.RABBITMQ_DLQ_QUEUE
        return args

    async def _push_redis_dlq(self, client: redis.Redis, reason: str, raw: str) -> None:
        try:
            await client.xadd(self._settings.REDIS_DLQ_STREAM, {"reason": reason, "raw": raw})
        except Exception:
            pass

    async def _push_rabbit_dlq(self, channel: aio_pika.Channel, reason: str, raw: bytes) -> None:
        try:
            message = aio_pika.Message(body=raw, headers={"reason": reason})
            dlq_exchange = await channel.declare_exchange(
                self._settings.RABBITMQ_DLQ_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )
            await dlq_exchange.publish(message, routing_key=self._settings.RABBITMQ_DLQ_QUEUE)
        except Exception:
            pass

    async def _maybe_trim_stream(self, client: redis.Redis, stream: str) -> None:
        if self._settings.REPLAY_STRATEGY != "bounded":
            return
        if self._settings.REPLAY_RETENTION_SECONDS <= 0:
            return
        now = time.time()
        last = self._last_stream_trim.get(stream, 0.0)
        interval = max(1.0, min(60.0, self._settings.REPLAY_RETENTION_SECONDS / 4))
        if now - last < interval:
            return
        min_id = f"{int((now - self._settings.REPLAY_RETENTION_SECONDS) * 1000)}-0"
        try:
            await client.xtrim(stream, minid=min_id)
        except Exception:
            pass
        self._last_stream_trim[stream] = now

    async def publish_broker(
        self,
        stream: Optional[str],
        exchange: Optional[aio_pika.Exchange],
        routing_key: str,
        payload: Dict[str, Any],
        body: Optional[str] = None,
    ) -> None:
        if body is None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if self.redis_publish_client and stream:
            try:
                kwargs: Dict[str, Any] = {}
                if self._settings.REPLAY_STRATEGY == "bounded" and self._settings.REPLAY_MAXLEN > 0:
                    kwargs["maxlen"] = self._settings.REPLAY_MAXLEN
                    kwargs["approximate"] = True
                await self.redis_publish_client.xadd(stream, {"data": body}, **kwargs)
                self._metrics.inc("broker_publish_total")
                await self._maybe_trim_stream(self.redis_publish_client, stream)
            except Exception:
                pass
        if exchange:
            try:
                message = aio_pika.Message(body=body.encode("utf-8"))
                await exchange.publish(message, routing_key=routing_key)
                self._metrics.inc("broker_publish_total")
            except Exception:
                pass

    async def _redis_outbox_consumer(self) -> None:
        if not self._settings.REDIS_DSN:
            return
        client = redis.from_url(self._settings.REDIS_DSN, decode_responses=True)
        last_id = "$" if self._settings.REPLAY_STRATEGY == "none" else "0-0"
        backoff = 1.0
        while True:
            try:
                response = await client.xread({self._settings.REDIS_STREAM: last_id}, block=5000, count=10)
                if not response:
                    backoff = 1.0
                    continue
                for _stream, messages in response:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        raw = fields.get("data", "{}")
                        try:
                            data = json.loads(raw)
                            subjects = data.get("subjects", [])
                            payload = self._strip_internal_payload(data.get("payload"))
                            traceparent = data.get("traceparent") or ""
                            span_ctx = self._tracing.extract_context(traceparent) if traceparent else None
                            if self._tracing.enabled and self._tracing.should_record(bool(traceparent)):
                                with self._tracing.tracer.start_as_current_span(
                                    "ws.outbox.redis", context=span_ctx, kind=SpanKind.CONSUMER
                                ) as span:
                                    span.set_attribute("ws.subjects_count", len(subjects))
                                    if self._send_to_subjects:
                                        await self._send_to_subjects(subjects, payload)
                            else:
                                if self._send_to_subjects:
                                    await self._send_to_subjects(subjects, payload)
                        except Exception:
                            await self._push_redis_dlq(client, "parse_error", raw)
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def _rabbit_outbox_consumer(self) -> None:
        if not self._settings.RABBITMQ_DSN:
            return
        backoff = 1.0
        while True:
            try:
                connection = await aio_pika.connect_robust(self._settings.RABBITMQ_DSN)
                async with connection:
                    channel = await connection.channel()
                    exchange = await channel.declare_exchange(
                        self._settings.RABBITMQ_EXCHANGE, ExchangeType.DIRECT, durable=True
                    )
                    dlq_exchange = await channel.declare_exchange(
                        self._settings.RABBITMQ_DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True
                    )
                    dlq_queue = await channel.declare_queue(self._settings.RABBITMQ_DLQ_QUEUE, durable=True)
                    await dlq_queue.bind(dlq_exchange, routing_key=self._settings.RABBITMQ_DLQ_QUEUE)
                    queue = await channel.declare_queue(
                        self._settings.RABBITMQ_QUEUE,
                        durable=True,
                        arguments=self._rabbit_queue_args(self._settings.RABBITMQ_QUEUE_TTL_MS),
                    )
                    await queue.bind(exchange, routing_key=self._settings.RABBITMQ_ROUTING_KEY)
                    async with queue.iterator() as queue_iter:
                        async for message in queue_iter:
                            async with message.process():
                                try:
                                    data = json.loads(message.body.decode("utf-8"))
                                    subjects = data.get("subjects", [])
                                    payload = self._strip_internal_payload(data.get("payload"))
                                    traceparent = data.get("traceparent") or ""
                                    span_ctx = self._tracing.extract_context(traceparent) if traceparent else None
                                    if self._tracing.enabled and self._tracing.should_record(bool(traceparent)):
                                        with self._tracing.tracer.start_as_current_span(
                                            "ws.outbox.rabbitmq", context=span_ctx, kind=SpanKind.CONSUMER
                                        ) as span:
                                            span.set_attribute("ws.subjects_count", len(subjects))
                                            if self._send_to_subjects:
                                                await self._send_to_subjects(subjects, payload)
                                    else:
                                        if self._send_to_subjects:
                                            await self._send_to_subjects(subjects, payload)
                                    backoff = 1.0
                                except Exception:
                                    await self._push_rabbit_dlq(channel, "parse_error", message.body)
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def _init_rabbitmq(self) -> None:
        backoff = 1.0
        while True:
            try:
                self.rabbit_publish_connection = await aio_pika.connect_robust(self._settings.RABBITMQ_DSN)
                self.rabbit_publish_channel = await self.rabbit_publish_connection.channel()
                self.rabbit_inbox_exchange = await self.rabbit_publish_channel.declare_exchange(
                    self._settings.RABBITMQ_INBOX_EXCHANGE,
                    ExchangeType.DIRECT,
                    durable=True,
                )
                self.rabbit_events_exchange = await self.rabbit_publish_channel.declare_exchange(
                    self._settings.RABBITMQ_EVENTS_EXCHANGE,
                    ExchangeType.DIRECT,
                    durable=True,
                )
                if self._settings.RABBITMQ_DLQ_EXCHANGE and self._settings.RABBITMQ_DLQ_QUEUE:
                    dlq_exchange = await self.rabbit_publish_channel.declare_exchange(
                        self._settings.RABBITMQ_DLQ_EXCHANGE,
                        ExchangeType.DIRECT,
                        durable=True,
                    )
                    dlq_queue = await self.rabbit_publish_channel.declare_queue(
                        self._settings.RABBITMQ_DLQ_QUEUE,
                        durable=True,
                    )
                    await dlq_queue.bind(dlq_exchange, routing_key=self._settings.RABBITMQ_DLQ_QUEUE)
                if self._settings.RABBITMQ_INBOX_QUEUE and self.rabbit_inbox_exchange:
                    inbox_queue = await self.rabbit_publish_channel.declare_queue(
                        self._settings.RABBITMQ_INBOX_QUEUE,
                        durable=True,
                        arguments=self._rabbit_queue_args(self._settings.RABBITMQ_INBOX_QUEUE_TTL_MS),
                    )
                    await inbox_queue.bind(self.rabbit_inbox_exchange, routing_key=self._settings.RABBITMQ_INBOX_ROUTING_KEY)
                if self._settings.RABBITMQ_EVENTS_QUEUE and self.rabbit_events_exchange:
                    events_queue = await self.rabbit_publish_channel.declare_queue(
                        self._settings.RABBITMQ_EVENTS_QUEUE,
                        durable=True,
                        arguments=self._rabbit_queue_args(self._settings.RABBITMQ_EVENTS_QUEUE_TTL_MS),
                    )
                    await events_queue.bind(self.rabbit_events_exchange, routing_key=self._settings.RABBITMQ_EVENTS_ROUTING_KEY)
                self._logger.logger.info("rabbitmq.connected")
                return
            except Exception as exc:
                self._logger.logger.warning("rabbitmq.connect_failed: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
