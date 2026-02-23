import json
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .broker import BrokerService
from .logging_service import LoggingService
from .message import InternalMessage
from .metrics import MetricsService
from .ordering import OrderingService
from .settings import Settings
from .tracing import TracingService
from .webhook import WebhookService


class EventPublisher:
    def __init__(
        self,
        settings: Settings,
        metrics: MetricsService,
        tracing: TracingService,
        ordering: OrderingService,
        broker: BrokerService,
        webhook: WebhookService,
        logger: LoggingService,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._tracing = tracing
        self._ordering = ordering
        self._broker = broker
        self._webhook = webhook
        self._logger = logger

    async def publish_event(
        self,
        event_type: str,
        stream: Optional[str],
        exchange,
        routing_key: str,
        payload: Dict[str, Any],
        ordering_key: str = "",
    ) -> None:
        stream, routing_key = self._ordering.apply_partition(stream, routing_key, ordering_key)
        body: Optional[str] = None

        def ensure_body() -> str:
            nonlocal body
            if body is None:
                body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            return body

        if self._settings.EVENTS_MODE in ("broker", "both"):
            if self._tracing.enabled and self._tracing.should_record(
                trace.get_current_span().get_span_context().is_valid
            ):
                with self._tracing.tracer.start_as_current_span("broker.publish", kind=SpanKind.PRODUCER) as span:
                    span.set_attribute("broker.routing_key", routing_key)
                    if stream:
                        span.set_attribute("broker.stream", stream)
                    await self._broker.publish_broker(stream, exchange, routing_key, payload, body=ensure_body())
            else:
                await self._broker.publish_broker(stream, exchange, routing_key, payload, body=ensure_body())
        if self._settings.EVENTS_MODE in ("webhook", "both"):
            if self._tracing.enabled and self._tracing.should_record(
                trace.get_current_span().get_span_context().is_valid
            ):
                with self._tracing.tracer.start_as_current_span("webhook.publish", kind=SpanKind.CLIENT) as span:
                    span.set_attribute("webhook.event_type", event_type)
                    await self._webhook.post(event_type, payload, body=ensure_body())
            else:
                await self._webhook.post(event_type, payload, body=ensure_body())

    async def publish_message_event(self, conn, data: Dict[str, Any], raw: str, internal: InternalMessage) -> None:
        traceparent = self._tracing.extract_traceparent(data) or conn.traceparent
        incoming_trace_id = self._tracing.extract_trace_id(data)
        has_parent = bool(traceparent or incoming_trace_id)
        span_ctx = self._tracing.extract_context(traceparent) if traceparent else None
        ordering_key = self._ordering.derive_ordering_key(conn, data)
        if self._settings.CHANNEL_ROUTING_STRATEGY == "channel_id" and internal.channel_id:
            ordering_key = internal.channel_id
        payload = {
            "type": "message_received",
            "schema_version": internal.schema_version,
            "internal_id": internal.internal_id,
            "timestamp_ms": internal.timestamp_ms,
            "user_id": internal.user_id,
            "channel_id": internal.channel_id,
            "flags": internal.flags.to_dict(),
            "payload": internal.payload,
            "connection_id": conn.id,
            "subjects": list(conn.subjects),
            "connected_at": conn.connected_at,
            "message": data,
            "raw": raw,
        }
        if traceparent:
            payload["traceparent"] = traceparent
        if incoming_trace_id:
            payload[self._settings.TRACING_TRACE_ID_FIELD] = incoming_trace_id
        if ordering_key:
            payload["ordering_key"] = ordering_key
            payload["ordering_strategy"] = (
                self._settings.CHANNEL_ROUTING_STRATEGY
                if self._settings.CHANNEL_ROUTING_STRATEGY == "channel_id"
                else self._settings.ORDERING_STRATEGY
            )

        if self._tracing.enabled and self._tracing.should_record(has_parent):
            with self._tracing.tracer.start_as_current_span(
                "ws.message", context=span_ctx, kind=SpanKind.SERVER
            ) as span:
                span.set_attribute("ws.connection_id", conn.id)
                span.set_attribute("ws.user_id", conn.user_id)
                span.set_attribute("ws.message_type", str(data.get("type", "")))
                self._tracing.inject_trace_context(payload)
                await self.publish_event(
                    "message_received",
                    self._settings.REDIS_INBOX_STREAM,
                    self._broker.rabbit_inbox_exchange,
                    self._settings.RABBITMQ_INBOX_ROUTING_KEY,
                    payload,
                    ordering_key=ordering_key,
                )
        else:
            await self.publish_event(
                "message_received",
                self._settings.REDIS_INBOX_STREAM,
                self._broker.rabbit_inbox_exchange,
                self._settings.RABBITMQ_INBOX_ROUTING_KEY,
                payload,
                ordering_key=ordering_key,
            )

    async def publish_connection_event(self, event_type: str, conn) -> None:
        traceparent = conn.traceparent
        has_parent = bool(traceparent)
        span_ctx = self._tracing.extract_context(traceparent) if traceparent else None
        payload = {
            "type": event_type,
            "connection_id": conn.id,
            "user_id": conn.user_id,
            "subjects": list(conn.subjects),
            "connected_at": conn.connected_at,
        }
        if traceparent:
            payload["traceparent"] = traceparent
        if self._tracing.enabled and self._tracing.should_record(has_parent):
            with self._tracing.tracer.start_as_current_span(
                f"ws.{event_type}", context=span_ctx, kind=SpanKind.SERVER
            ) as span:
                span.set_attribute("ws.connection_id", conn.id)
                span.set_attribute("ws.user_id", conn.user_id)
                self._tracing.inject_trace_context(payload)
                await self.publish_event(
                    event_type,
                    self._settings.REDIS_EVENTS_STREAM,
                    self._broker.rabbit_events_exchange,
                    self._settings.RABBITMQ_EVENTS_ROUTING_KEY,
                    payload,
                )
        else:
            await self.publish_event(
                event_type,
                self._settings.REDIS_EVENTS_STREAM,
                self._broker.rabbit_events_exchange,
                self._settings.RABBITMQ_EVENTS_ROUTING_KEY,
                payload,
            )
