import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from opentelemetry.trace import SpanKind

from .auth import JwtAuthenticator
from .backpressure import BackpressureManager
from .broker import BrokerService
from .connections import Connection, ConnectionManager
from .events import EventPublisher
from .logging_service import LoggingService
from .message import InternalMessage, extract_channel_id, extract_flags, extract_payload
from .metrics import MetricsService
from .ordering import OrderingService
from .presence import PresenceService
from .rate_limit import build_idempotency_store, build_rate_limiter
from .replay import ReplayService
from .settings import Settings
from .tracing import TracingService
from .snowflake import SnowflakeGenerator
from .webhook import WebhookService

SIMPLE_PING = '{"type":"ping"}'
SIMPLE_HEARTBEAT = '{"type":"heartbeat"}'
PONG_MESSAGE = '{"type":"pong"}'
HEARTBEAT_ACK_MESSAGE = '{"type":"heartbeat_ack"}'
RATE_LIMITED_MESSAGE = '{"type":"rate_limited"}'
READ_ONLY_MESSAGE = '{"type":"read_only"}'


def _is_exact_json(message: str, expected: str) -> bool:
    trimmed = message.strip()
    return len(trimmed) == len(expected) and trimmed == expected


def _extract_channels(query_params) -> list[str]:
    channels: list[str] = []
    raw = query_params.get("channels")
    if raw:
        for item in raw.split(","):
            item = item.strip()
            if item:
                channels.append(item)
    raw = query_params.get("channel")
    if raw:
        item = raw.strip()
        if item:
            channels.append(item)
    return channels


class GatewayApp:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metrics = MetricsService()
        self._logger = LoggingService(settings)
        self._tracing = TracingService(settings)
        self._auth = JwtAuthenticator(settings)
        self._ordering = OrderingService(settings)
        self._backpressure = BackpressureManager(settings)
        self._presence = PresenceService(settings)
        self._connections = ConnectionManager(settings)
        self._broker = BrokerService(settings, self._metrics, self._tracing, self._logger)
        self._webhook = WebhookService(settings, self._metrics, self._tracing, self._logger)
        self._events = EventPublisher(
            settings,
            self._metrics,
            self._tracing,
            self._ordering,
            self._broker,
            self._webhook,
            self._logger,
        )
        self._broker.set_sender(self._connections.send_to_subjects)
        self._snowflake = (
            SnowflakeGenerator(settings.SNOWFLAKE_WORKER_ID, settings.SNOWFLAKE_EPOCH_MS)
            if settings.SNOWFLAKE_ENABLED and settings.ROLE_WRITE
            else None
        )
        self._replay = ReplayService(
            settings,
            self._metrics,
            self._logger,
            build_rate_limiter(settings),
            build_idempotency_store(settings),
        )

    def _next_internal_id(self) -> str:
        if self._snowflake:
            return self._snowflake.next_id_str()
        return str(uuid.uuid4())

    async def startup_tasks(self) -> None:
        self._tracing.init_tracing()
        self._backpressure.configure()
        await self._presence.startup()
        await self._broker.startup()
        await self._webhook.startup()

    async def shutdown_tasks(self) -> None:
        await self._webhook.shutdown()
        await self._broker.shutdown()

    async def _handle_control_message(self, websocket: WebSocket, conn: Connection, msg_type: str) -> None:
        if self._settings.PRESENCE_STRATEGY in ("ttl", "heartbeat"):
            if msg_type == "heartbeat" or self._settings.PRESENCE_REFRESH_ON_MESSAGE:
                self._presence.refresh(conn)
        if msg_type == "ping":
            await websocket.send_text(PONG_MESSAGE)
        else:
            await websocket.send_text(HEARTBEAT_ACK_MESSAGE)

    async def ws_endpoint(self, websocket: WebSocket) -> None:
        token = websocket.headers.get("authorization", "").replace("Bearer ", "")
        if not token:
            token = websocket.query_params.get("token", "")
        if not token:
            token = websocket.query_params.get("access_token", "")
        if not token:
            await websocket.close(code=4401)
            return
        try:
            claims = await self._auth.verify(token)
        except Exception:
            await websocket.close(code=4401)
            return
        user_id = str(claims.get(self._settings.JWT_USER_ID_CLAIM, ""))
        if not user_id:
            await websocket.close(code=4401)
            return

        subjects = [f"user:{user_id}"]
        for channel in _extract_channels(websocket.query_params):
            subjects.append(f"channel:{channel}")

        await websocket.accept()
        conn = self._connections.add(websocket, user_id, subjects)

        self._metrics.inc("ws_connections_total")
        self._logger.log("ws_connected", connection_id=conn.id, user_id=conn.user_id, subjects=list(conn.subjects))
        asyncio.create_task(self._presence.set(conn))
        asyncio.create_task(self._events.publish_connection_event("connected", conn))

        try:
            while True:
                msg = await websocket.receive_text()
                if _is_exact_json(msg, SIMPLE_PING):
                    await self._handle_control_message(websocket, conn, "ping")
                    continue
                if _is_exact_json(msg, SIMPLE_HEARTBEAT):
                    await self._handle_control_message(websocket, conn, "heartbeat")
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    data = {"type": "raw", "payload": msg}
                msg_type = data.get("type")
                if msg_type in ("ping", "heartbeat"):
                    await self._handle_control_message(websocket, conn, msg_type)
                    continue
                if not conn.allow_message():
                    await websocket.send_text(RATE_LIMITED_MESSAGE)
                    self._metrics.inc("ws_rate_limited_total")
                    self._logger.log("ws_rate_limited", connection_id=conn.id, user_id=conn.user_id)
                    continue
                self._metrics.inc("ws_messages_total")
                if not self._settings.ROLE_WRITE:
                    await websocket.send_text(READ_ONLY_MESSAGE)
                    continue
                if self._settings.PRESENCE_STRATEGY in ("ttl", "heartbeat") and self._settings.PRESENCE_REFRESH_ON_MESSAGE:
                    self._presence.refresh(conn)
                internal_id = self._next_internal_id()
                timestamp_ms = int(time.time() * 1000)
                channel_fallback = conn.user_id
                for subject in conn.subjects:
                    if subject.startswith("channel:"):
                        channel_fallback = subject.split(":", 1)[1]
                        break
                channel_id = extract_channel_id(data, channel_fallback)
                flags = extract_flags(data)
                payload = extract_payload(data)
                internal = InternalMessage(
                    schema_version=1,
                    internal_id=internal_id,
                    timestamp_ms=timestamp_ms,
                    user_id=conn.user_id,
                    channel_id=channel_id,
                    flags=flags,
                    payload=payload,
                )

                if self._settings.BACKPRESSURE_STRATEGY == "none":
                    asyncio.create_task(self._events.publish_message_event(conn, data, msg, internal))
                    continue
                acquired = await self._backpressure.try_acquire_inflight()
                if acquired:
                    asyncio.create_task(self._publish_with_inflight(conn, data, msg, internal))
                    continue
                if self._settings.BACKPRESSURE_STRATEGY == "drop":
                    self._metrics.inc("backpressure_dropped_total")
                    self._logger.log("backpressure_drop", connection_id=conn.id, user_id=conn.user_id)
                    continue
                if self._settings.BACKPRESSURE_STRATEGY == "close":
                    self._metrics.inc("backpressure_closed_total")
                    self._logger.log("backpressure_close", connection_id=conn.id, user_id=conn.user_id)
                    await websocket.close(code=1013)
                    break
                if self._settings.BACKPRESSURE_STRATEGY == "buffer":
                    await self._buffer_message(conn, data, msg, internal)
        except WebSocketDisconnect:
            pass
        finally:
            self._metrics.inc("ws_disconnects_total")
            self._logger.log("ws_disconnected", connection_id=conn.id, user_id=conn.user_id)
            await self._connections.remove(conn)
            if conn.buffer_task and not conn.buffer_task.done():
                conn.buffer_task.cancel()
            dropped = len(conn.buffer)
            if dropped:
                conn.buffer.clear()
                for _ in range(dropped):
                    self._backpressure.release_buffer_slot()
            asyncio.create_task(self._presence.remove(conn))
            asyncio.create_task(self._events.publish_connection_event("disconnected", conn))

    async def _publish_with_inflight(
        self,
        conn: Connection,
        data: Dict[str, Any],
        raw: str,
        internal: InternalMessage,
    ) -> None:
        try:
            await self._events.publish_message_event(conn, data, raw, internal)
        finally:
            self._backpressure.release_inflight()

    async def _drain_buffer(self, conn: Connection) -> None:
        while True:
            await conn.buffer_event.wait()
            while conn.buffer:
                await self._backpressure.acquire_inflight()
                data, raw, internal = conn.buffer.popleft()
                self._backpressure.release_buffer_slot()
                asyncio.create_task(self._publish_with_inflight(conn, data, raw, internal))
            conn.buffer_event.clear()
            if conn.id not in self._connections.connections:
                return

    async def _buffer_message(self, conn: Connection, data: Dict[str, Any], raw: str, internal: InternalMessage) -> None:
        if self._settings.BACKPRESSURE_PER_CONN_BUFFER <= 0:
            self._metrics.inc("backpressure_dropped_total")
            return
        if len(conn.buffer) >= self._settings.BACKPRESSURE_PER_CONN_BUFFER:
            if self._settings.BACKPRESSURE_DROP_POLICY == "oldest" and conn.buffer:
                conn.buffer.popleft()
                self._backpressure.release_buffer_slot()
                self._metrics.inc("backpressure_dropped_total")
            else:
                self._metrics.inc("backpressure_dropped_total")
                return
        if not await self._backpressure.try_acquire_buffer_slot():
            if self._settings.BACKPRESSURE_DROP_POLICY == "oldest" and conn.buffer:
                conn.buffer.popleft()
                self._backpressure.release_buffer_slot()
                if not await self._backpressure.try_acquire_buffer_slot():
                    self._metrics.inc("backpressure_dropped_total")
                    return
                self._metrics.inc("backpressure_dropped_total")
            else:
                self._metrics.inc("backpressure_dropped_total")
                return
        conn.buffer.append((data, raw, internal))
        self._metrics.inc("backpressure_buffered_total")
        if not conn.buffer_task or conn.buffer_task.done():
            conn.buffer_task = asyncio.create_task(self._drain_buffer(conn))
        conn.buffer_event.set()

    async def publish(self, payload: Dict[str, Any], request: Request):
        if not self._settings.ROLE_READ:
            raise HTTPException(status_code=403, detail="read role required")
        api_key = payload.get("api_key") or ""
        if self._settings.GATEWAY_API_KEY and api_key != self._settings.GATEWAY_API_KEY:
            raise HTTPException(status_code=401, detail="invalid api key")

        subjects = payload.get("subjects", [])
        message = payload.get("payload")
        traceparent = request.headers.get("traceparent", "")
        span_ctx = self._tracing.extract_context(traceparent) if traceparent else None

        if self._tracing.enabled and self._tracing.should_record(bool(traceparent)):
            with self._tracing.tracer.start_as_current_span("ws.publish.http", context=span_ctx, kind=SpanKind.SERVER) as span:
                span.set_attribute("ws.subjects_count", len(subjects))
                sent = await self._connections.send_to_subjects(subjects, message)
        else:
            sent = await self._connections.send_to_subjects(subjects, message)
        self._metrics.inc("publish_total")
        return JSONResponse({"sent": sent})

    async def replay_rabbitmq(self, payload: Dict[str, Any], request: Request):
        if not self._settings.ROLE_WRITE:
            raise HTTPException(status_code=403, detail="write role required")
        result = await self._replay.handle(payload, request)
        return JSONResponse(result)

    async def metrics_endpoint(self):
        return PlainTextResponse(self._metrics.to_prometheus())

    async def health(self):
        return JSONResponse({"ok": True})

    async def ready(self):
        return JSONResponse({"ok": True})

    async def list_connections(self, subject: Optional[str] = None, user_id: Optional[str] = None):
        results = []
        for conn in self._connections.connections.values():
            if subject and subject not in conn.subjects:
                continue
            if user_id and user_id != conn.user_id:
                continue
            results.append(
                {
                    "connection_id": conn.id,
                    "user_id": conn.user_id,
                    "subjects": list(conn.subjects),
                    "connected_at": conn.connected_at,
                }
            )
        return JSONResponse({"connections": results})

    async def user_connections(self, user_id: str):
        results = []
        for conn in self._connections.connections.values():
            if user_id != conn.user_id:
                continue
            results.append(
                {
                    "connection_id": conn.id,
                    "user_id": conn.user_id,
                    "subjects": list(conn.subjects),
                    "connected_at": conn.connected_at,
                }
            )
        return JSONResponse({"connections": results})
