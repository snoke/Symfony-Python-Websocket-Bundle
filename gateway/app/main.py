import asyncio
import json
import os
import time
import uuid
import hashlib
import hmac
import logging
import random
import sys
from typing import Any, Dict, List, Optional, Set

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OtlpHttpSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import SpanKind, format_trace_id

import aio_pika
import httpx
import jwt
import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from jwt import PyJWKClient
from aio_pika import ExchangeType

app = FastAPI()

JWT_ALG = os.getenv("JWT_ALG", "RS256")
JWT_USER_ID_CLAIM = os.getenv("JWT_USER_ID_CLAIM", "user_id")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_PUBLIC_KEY_FILE = os.getenv("JWT_PUBLIC_KEY_FILE", "")
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "")
JWT_ISSUER = os.getenv("JWT_ISSUER", "")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "")
JWT_LEEWAY = int(os.getenv("JWT_LEEWAY", "0"))
WS_MODE = os.getenv("WS_MODE", "terminator")
EVENTS_MODE = os.getenv("EVENTS_MODE", "")
if not EVENTS_MODE:
    EVENTS_MODE = "broker" if WS_MODE == "core" else "webhook"
EVENTS_MODE = EVENTS_MODE.lower()
if EVENTS_MODE not in ("broker", "webhook", "both", "none"):
    EVENTS_MODE = "broker" if WS_MODE == "core" else "webhook"
SYMFONY_WEBHOOK_URL = os.getenv("SYMFONY_WEBHOOK_URL", "")
SYMFONY_WEBHOOK_SECRET = os.getenv("SYMFONY_WEBHOOK_SECRET", "")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
REDIS_DSN = os.getenv("REDIS_DSN", "")
REDIS_STREAM = os.getenv("REDIS_STREAM", "ws.outbox")
RABBITMQ_DSN = os.getenv("RABBITMQ_DSN", "")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "ws.outbox")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "ws.outbox")
RABBITMQ_ROUTING_KEY = os.getenv("RABBITMQ_ROUTING_KEY", "ws.outbox")
RABBITMQ_INBOX_EXCHANGE = os.getenv("RABBITMQ_INBOX_EXCHANGE", "ws.inbox")
RABBITMQ_INBOX_ROUTING_KEY = os.getenv("RABBITMQ_INBOX_ROUTING_KEY", "ws.inbox")
RABBITMQ_EVENTS_EXCHANGE = os.getenv("RABBITMQ_EVENTS_EXCHANGE", "ws.events")
RABBITMQ_EVENTS_ROUTING_KEY = os.getenv("RABBITMQ_EVENTS_ROUTING_KEY", "ws.events")
RABBITMQ_DLQ_QUEUE = os.getenv("RABBITMQ_DLQ_QUEUE", "ws.dlq")
RABBITMQ_DLQ_EXCHANGE = os.getenv("RABBITMQ_DLQ_EXCHANGE", "ws.dlq")
REDIS_DLQ_STREAM = os.getenv("REDIS_DLQ_STREAM", "ws.dlq")
REDIS_INBOX_STREAM = os.getenv("REDIS_INBOX_STREAM", "ws.inbox")
REDIS_EVENTS_STREAM = os.getenv("REDIS_EVENTS_STREAM", "ws.events")
PRESENCE_REDIS_DSN = os.getenv("PRESENCE_REDIS_DSN", REDIS_DSN)
PRESENCE_REDIS_PREFIX = os.getenv("PRESENCE_REDIS_PREFIX", "presence:")
PRESENCE_TTL_SECONDS = int(os.getenv("PRESENCE_TTL_SECONDS", "120"))
WEBHOOK_RETRY_ATTEMPTS = int(os.getenv("WEBHOOK_RETRY_ATTEMPTS", "3"))
WEBHOOK_RETRY_BASE_SECONDS = float(os.getenv("WEBHOOK_RETRY_BASE_SECONDS", "0.5"))
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
TRACING_STRATEGY = os.getenv("TRACING_STRATEGY", "none").lower()
TRACING_TRACE_ID_FIELD = os.getenv("TRACING_TRACE_ID_FIELD", "trace_id")
TRACING_HEADER_NAME = os.getenv("TRACING_HEADER_NAME", "X-Trace-Id")
TRACING_SAMPLE_RATE = float(os.getenv("TRACING_SAMPLE_RATE", "1.0"))
TRACING_EXPORTER = os.getenv("TRACING_EXPORTER", "stdout").lower()
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "gateway")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTEL_EXPORTER_OTLP_PROTOCOL = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf").lower()
WS_RATE_LIMIT_PER_SEC = float(os.getenv("WS_RATE_LIMIT_PER_SEC", "10"))
WS_RATE_LIMIT_BURST = float(os.getenv("WS_RATE_LIMIT_BURST", "20"))
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

if TRACING_STRATEGY not in ("none", "propagate", "full"):
    TRACING_STRATEGY = "none"
if TRACING_SAMPLE_RATE < 0:
    TRACING_SAMPLE_RATE = 0.0
if TRACING_SAMPLE_RATE > 1:
    TRACING_SAMPLE_RATE = 1.0
if TRACING_EXPORTER not in ("stdout", "otlp", "none"):
    TRACING_EXPORTER = "stdout"

logger = logging.getLogger("gateway")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logger.level)
logger.addHandler(handler)

metrics: Dict[str, int] = {
    "ws_connections_total": 0,
    "ws_disconnects_total": 0,
    "ws_messages_total": 0,
    "ws_rate_limited_total": 0,
    "publish_total": 0,
    "broker_publish_total": 0,
    "webhook_publish_total": 0,
    "webhook_publish_failed_total": 0,
}

tracer = trace.get_tracer("gateway")
tracing_enabled = False

redis_publish_client: Optional[redis.Redis] = None
presence_client: Optional[redis.Redis] = None
rabbit_publish_connection: Optional[aio_pika.RobustConnection] = None
rabbit_publish_channel: Optional[aio_pika.Channel] = None
rabbit_inbox_exchange: Optional[aio_pika.Exchange] = None
rabbit_events_exchange: Optional[aio_pika.Exchange] = None
http_client: Optional[httpx.AsyncClient] = None

def _log(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    if LOG_FORMAT == "json":
        logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    else:
        logger.info("%s %s", event, payload)

def _create_otlp_exporter():
    if OTEL_EXPORTER_OTLP_PROTOCOL.startswith("grpc"):
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as OtlpGrpcSpanExporter

        return OtlpGrpcSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
    return OtlpHttpSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)

def _init_tracing() -> None:
    global tracer, tracing_enabled
    if TRACING_STRATEGY == "none" or TRACING_EXPORTER == "none":
        return
    resource = Resource.create({"service.name": OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    if TRACING_EXPORTER == "otlp" and OTEL_EXPORTER_OTLP_ENDPOINT:
        exporter = _create_otlp_exporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("gateway")
    tracing_enabled = True

def _should_sample_trace() -> bool:
    if TRACING_SAMPLE_RATE <= 0:
        return False
    if TRACING_SAMPLE_RATE >= 1:
        return True
    return random.random() < TRACING_SAMPLE_RATE

def _should_record(has_parent: bool) -> bool:
    if TRACING_STRATEGY == "none":
        return False
    if TRACING_STRATEGY == "propagate" and not has_parent:
        return False
    return _should_sample_trace()

def _extract_traceparent(data: Optional[Dict[str, Any]]) -> str:
    if not data:
        return ""
    traceparent = data.get("traceparent")
    if traceparent is None and isinstance(data.get("meta"), dict):
        traceparent = data["meta"].get("traceparent")
    return str(traceparent) if traceparent else ""

def _extract_trace_id(data: Optional[Dict[str, Any]]) -> str:
    if not data:
        return ""
    trace_id = data.get(TRACING_TRACE_ID_FIELD)
    if trace_id is None and isinstance(data.get("meta"), dict):
        trace_id = data["meta"].get(TRACING_TRACE_ID_FIELD)
    return str(trace_id) if trace_id else ""

def _inject_trace_context(payload: Dict[str, Any]) -> None:
    carrier: Dict[str, str] = {}
    propagate.inject(carrier)
    traceparent = carrier.get("traceparent")
    if traceparent:
        payload["traceparent"] = traceparent
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        if TRACING_TRACE_ID_FIELD not in payload or not payload.get(TRACING_TRACE_ID_FIELD):
            payload[TRACING_TRACE_ID_FIELD] = format_trace_id(span.get_span_context().trace_id)

class Connection:
    def __init__(self, websocket: WebSocket, user_id: str, subjects: List[str]):
        self.id = str(uuid.uuid4())
        self.websocket = websocket
        self.user_id = user_id
        self.subjects = set(subjects)
        self.connected_at = int(time.time())
        self.traceparent = websocket.headers.get("traceparent", "")
        self._tokens = WS_RATE_LIMIT_BURST
        self._last_refill = time.time()

    def allow_message(self) -> bool:
        if WS_RATE_LIMIT_PER_SEC <= 0:
            return True
        now = time.time()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(WS_RATE_LIMIT_BURST, self._tokens + elapsed * WS_RATE_LIMIT_PER_SEC)
        self._last_refill = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

connections: Dict[str, Connection] = {}
subjects_index: Dict[str, Set[str]] = {}

async def _send_to_subjects(subjects: List[str], payload: Any) -> int:
    sent = 0
    target_ids: Set[str] = set()
    for s in subjects:
        for cid in subjects_index.get(s, set()):
            target_ids.add(cid)
    for cid in target_ids:
        conn = connections.get(cid)
        if conn is None:
            continue
        try:
            await conn.websocket.send_json({"type": "event", "payload": payload})
            sent += 1
        except Exception:
            pass
    return sent


async def _post_webhook(event_type: str, payload: Dict[str, Any]) -> None:
    if EVENTS_MODE not in ("webhook", "both"):
        return
    if not SYMFONY_WEBHOOK_URL or not http_client:
        return
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    headers: Dict[str, str] = {}
    if SYMFONY_WEBHOOK_SECRET:
        signature = hmac.new(
            SYMFONY_WEBHOOK_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    trace_id = payload.get(TRACING_TRACE_ID_FIELD)
    if trace_id and TRACING_HEADER_NAME:
        headers[TRACING_HEADER_NAME] = str(trace_id)
    carrier: Dict[str, str] = {}
    propagate.inject(carrier)
    if "traceparent" in carrier:
        headers["traceparent"] = carrier["traceparent"]
    elif "traceparent" in payload:
        headers["traceparent"] = str(payload["traceparent"])
    for attempt in range(WEBHOOK_RETRY_ATTEMPTS):
        try:
            await http_client.post(SYMFONY_WEBHOOK_URL, content=body, headers=headers)
            metrics["webhook_publish_total"] += 1
            return
        except Exception:
            await asyncio.sleep(WEBHOOK_RETRY_BASE_SECONDS * (2 ** attempt))
    metrics["webhook_publish_failed_total"] += 1
    _log("webhook_failed", type=event_type, connection_id=payload.get("connection_id"), user_id=payload.get("user_id"))


async def _push_redis_dlq(client: redis.Redis, reason: str, raw: str) -> None:
    try:
        await client.xadd(REDIS_DLQ_STREAM, {"reason": reason, "raw": raw})
    except Exception:
        pass

async def _push_rabbit_dlq(channel: aio_pika.Channel, reason: str, raw: bytes) -> None:
    try:
        message = aio_pika.Message(body=raw, headers={"reason": reason})
        dlq_exchange = await channel.declare_exchange(RABBITMQ_DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True)
        await dlq_exchange.publish(message, routing_key=RABBITMQ_DLQ_QUEUE)
    except Exception:
        pass

async def _publish_broker(stream: Optional[str], exchange: Optional[aio_pika.Exchange], routing_key: str, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if redis_publish_client and stream:
        try:
            await redis_publish_client.xadd(stream, {"data": body})
            metrics["broker_publish_total"] += 1
        except Exception:
            pass
    if exchange:
        try:
            message = aio_pika.Message(body=body.encode("utf-8"))
            await exchange.publish(message, routing_key=routing_key)
            metrics["broker_publish_total"] += 1
        except Exception:
            pass

async def _publish_event(event_type: str, stream: Optional[str], exchange: Optional[aio_pika.Exchange], routing_key: str, payload: Dict[str, Any]) -> None:
    if EVENTS_MODE in ("broker", "both"):
        if tracing_enabled and _should_record(trace.get_current_span().get_span_context().is_valid):
            with tracer.start_as_current_span("broker.publish", kind=SpanKind.PRODUCER) as span:
                span.set_attribute("broker.routing_key", routing_key)
                if stream:
                    span.set_attribute("broker.stream", stream)
                await _publish_broker(stream, exchange, routing_key, payload)
        else:
            await _publish_broker(stream, exchange, routing_key, payload)
    if EVENTS_MODE in ("webhook", "both"):
        if tracing_enabled and _should_record(trace.get_current_span().get_span_context().is_valid):
            with tracer.start_as_current_span("webhook.publish", kind=SpanKind.CLIENT) as span:
                span.set_attribute("webhook.event_type", event_type)
                await _post_webhook(event_type, payload)
        else:
            await _post_webhook(event_type, payload)

async def _publish_message_event(conn: Connection, data: Dict[str, Any], raw: str) -> None:
    traceparent = _extract_traceparent(data) or conn.traceparent
    incoming_trace_id = _extract_trace_id(data)
    has_parent = bool(traceparent or incoming_trace_id)
    span_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None

    payload = {
        "type": "message_received",
        "connection_id": conn.id,
        "user_id": conn.user_id,
        "subjects": list(conn.subjects),
        "connected_at": conn.connected_at,
        "message": data,
        "raw": raw,
    }

    if traceparent:
        payload["traceparent"] = traceparent
    if incoming_trace_id:
        payload[TRACING_TRACE_ID_FIELD] = incoming_trace_id

    if tracing_enabled and _should_record(has_parent):
        with tracer.start_as_current_span("ws.message", context=span_ctx, kind=SpanKind.SERVER) as span:
            span.set_attribute("ws.connection_id", conn.id)
            span.set_attribute("ws.user_id", conn.user_id)
            span.set_attribute("ws.message_type", str(data.get("type", "")))
            _inject_trace_context(payload)
            await _publish_event(
                "message_received",
                REDIS_INBOX_STREAM,
                rabbit_inbox_exchange,
                RABBITMQ_INBOX_ROUTING_KEY,
                payload,
            )
    else:
        await _publish_event("message_received", REDIS_INBOX_STREAM, rabbit_inbox_exchange, RABBITMQ_INBOX_ROUTING_KEY, payload)

async def _publish_connection_event(event_type: str, conn: Connection) -> None:
    traceparent = conn.traceparent
    has_parent = bool(traceparent)
    span_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None
    payload = {
        "type": event_type,
        "connection_id": conn.id,
        "user_id": conn.user_id,
        "subjects": list(conn.subjects),
        "connected_at": conn.connected_at,
    }
    if traceparent:
        payload["traceparent"] = traceparent
    if tracing_enabled and _should_record(has_parent):
        with tracer.start_as_current_span(f"ws.{event_type}", context=span_ctx, kind=SpanKind.SERVER) as span:
            span.set_attribute("ws.connection_id", conn.id)
            span.set_attribute("ws.user_id", conn.user_id)
            _inject_trace_context(payload)
            await _publish_event(event_type, REDIS_EVENTS_STREAM, rabbit_events_exchange, RABBITMQ_EVENTS_ROUTING_KEY, payload)
    else:
        await _publish_event(event_type, REDIS_EVENTS_STREAM, rabbit_events_exchange, RABBITMQ_EVENTS_ROUTING_KEY, payload)

async def _presence_set(conn: Connection) -> None:
    if not presence_client:
        return
    prefix = PRESENCE_REDIS_PREFIX
    conn_key = f"{prefix}conn:{conn.id}"
    data = {
        "connection_id": conn.id,
        "user_id": conn.user_id,
        "subjects": json.dumps(list(conn.subjects)),
        "connected_at": str(conn.connected_at),
    }
    await presence_client.hset(conn_key, mapping=data)
    if PRESENCE_TTL_SECONDS > 0:
        await presence_client.expire(conn_key, PRESENCE_TTL_SECONDS)
    user_key = f"{prefix}user:{conn.user_id}"
    await presence_client.sadd(user_key, conn.id)
    if PRESENCE_TTL_SECONDS > 0:
        await presence_client.expire(user_key, PRESENCE_TTL_SECONDS)
    for subject in conn.subjects:
        subject_key = f"{prefix}subject:{subject}"
        await presence_client.sadd(subject_key, conn.id)
        if PRESENCE_TTL_SECONDS > 0:
            await presence_client.expire(subject_key, PRESENCE_TTL_SECONDS)

async def _presence_remove(conn: Connection) -> None:
    if not presence_client:
        return
    prefix = PRESENCE_REDIS_PREFIX
    await presence_client.delete(f"{prefix}conn:{conn.id}")
    await presence_client.srem(f"{prefix}user:{conn.user_id}", conn.id)
    for subject in conn.subjects:
        await presence_client.srem(f"{prefix}subject:{subject}", conn.id)

async def _verify_jwt(token: str) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if JWT_ISSUER:
        kwargs["issuer"] = JWT_ISSUER
    if JWT_AUDIENCE:
        kwargs["audience"] = JWT_AUDIENCE
    if JWT_LEEWAY:
        kwargs["leeway"] = JWT_LEEWAY
    if JWT_JWKS_URL:
        jwk_client = PyJWKClient(JWT_JWKS_URL)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, algorithms=[JWT_ALG], **kwargs)
    if JWT_PUBLIC_KEY_FILE and os.path.exists(JWT_PUBLIC_KEY_FILE):
        with open(JWT_PUBLIC_KEY_FILE, "r", encoding="utf-8") as f:
            public_key = f.read()
        return jwt.decode(token, public_key, algorithms=[JWT_ALG], **kwargs)
    if JWT_PUBLIC_KEY:
        return jwt.decode(token, JWT_PUBLIC_KEY, algorithms=[JWT_ALG], **kwargs)
    raise HTTPException(status_code=500, detail="JWT config missing")

async def _redis_outbox_consumer() -> None:
    if not REDIS_DSN:
        return
    client = redis.from_url(REDIS_DSN, decode_responses=True)
    last_id = "0-0"
    backoff = 1.0
    while True:
        try:
            response = await client.xread({REDIS_STREAM: last_id}, block=5000, count=10)
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
                        payload = data.get("payload")
                        traceparent = data.get("traceparent") or ""
                        span_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None
                        if tracing_enabled and _should_record(bool(traceparent)):
                            with tracer.start_as_current_span("ws.outbox.redis", context=span_ctx, kind=SpanKind.CONSUMER) as span:
                                span.set_attribute("ws.subjects_count", len(subjects))
                                await _send_to_subjects(subjects, payload)
                        else:
                            await _send_to_subjects(subjects, payload)
                    except Exception:
                        await _push_redis_dlq(client, "parse_error", raw)
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)

async def _rabbit_outbox_consumer() -> None:
    if not RABBITMQ_DSN:
        return
    backoff = 1.0
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_DSN)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(RABBITMQ_EXCHANGE, ExchangeType.DIRECT, durable=True)
                dlq_exchange = await channel.declare_exchange(RABBITMQ_DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True)
                dlq_queue = await channel.declare_queue(RABBITMQ_DLQ_QUEUE, durable=True)
                await dlq_queue.bind(dlq_exchange, routing_key=RABBITMQ_DLQ_QUEUE)
                queue = await channel.declare_queue(RABBITMQ_QUEUE, durable=True)
                await queue.bind(exchange, routing_key=RABBITMQ_ROUTING_KEY)
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            try:
                                data = json.loads(message.body.decode("utf-8"))
                                subjects = data.get("subjects", [])
                                payload = data.get("payload")
                                traceparent = data.get("traceparent") or ""
                                span_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None
                                if tracing_enabled and _should_record(bool(traceparent)):
                                    with tracer.start_as_current_span("ws.outbox.rabbitmq", context=span_ctx, kind=SpanKind.CONSUMER) as span:
                                        span.set_attribute("ws.subjects_count", len(subjects))
                                        await _send_to_subjects(subjects, payload)
                                else:
                                    await _send_to_subjects(subjects, payload)
                                backoff = 1.0
                            except Exception:
                                await _push_rabbit_dlq(channel, "parse_error", message.body)
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)

@app.on_event("startup")
async def startup_tasks() -> None:
    global redis_publish_client, presence_client, http_client
    global rabbit_publish_connection, rabbit_publish_channel, rabbit_inbox_exchange, rabbit_events_exchange
    _init_tracing()
    if REDIS_DSN:
        redis_publish_client = redis.from_url(REDIS_DSN, decode_responses=True)
    if PRESENCE_REDIS_DSN:
        presence_client = redis.from_url(PRESENCE_REDIS_DSN, decode_responses=True)
    if RABBITMQ_DSN:
        rabbit_publish_connection = await aio_pika.connect_robust(RABBITMQ_DSN)
        rabbit_publish_channel = await rabbit_publish_connection.channel()
        rabbit_inbox_exchange = await rabbit_publish_channel.declare_exchange(
            RABBITMQ_INBOX_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )
        rabbit_events_exchange = await rabbit_publish_channel.declare_exchange(
            RABBITMQ_EVENTS_EXCHANGE,
            ExchangeType.DIRECT,
            durable=True,
        )
    if REDIS_DSN:
        asyncio.create_task(_redis_outbox_consumer())
    if RABBITMQ_DSN:
        asyncio.create_task(_rabbit_outbox_consumer())
    if EVENTS_MODE in ("webhook", "both") and SYMFONY_WEBHOOK_URL:
        http_client = httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS)

@app.on_event("shutdown")
async def shutdown_tasks() -> None:
    global http_client
    if http_client:
        await http_client.aclose()
        http_client = None
    if rabbit_publish_connection:
        await rabbit_publish_connection.close()

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    token = websocket.headers.get("authorization", "").replace("Bearer ", "")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        claims = await _verify_jwt(token)
    except Exception:
        await websocket.close(code=4401)
        return
    user_id = str(claims.get(JWT_USER_ID_CLAIM, ""))
    if not user_id:
        await websocket.close(code=4401)
        return

    subjects = [f"user:{user_id}"]

    await websocket.accept()
    conn = Connection(websocket, user_id, subjects)
    connections[conn.id] = conn
    for s in conn.subjects:
        subjects_index.setdefault(s, set()).add(conn.id)

    metrics["ws_connections_total"] += 1
    _log("ws_connected", connection_id=conn.id, user_id=conn.user_id, subjects=list(conn.subjects))
    asyncio.create_task(_presence_set(conn))
    asyncio.create_task(_publish_connection_event("connected", conn))

    try:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                data = {"type": "raw", "payload": msg}
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if not conn.allow_message():
                await websocket.send_json({"type": "rate_limited"})
                metrics["ws_rate_limited_total"] += 1
                _log("ws_rate_limited", connection_id=conn.id, user_id=conn.user_id)
                continue
            metrics["ws_messages_total"] += 1
            asyncio.create_task(_publish_message_event(conn, data, msg))
    except WebSocketDisconnect:
        pass
    finally:
        metrics["ws_disconnects_total"] += 1
        _log("ws_disconnected", connection_id=conn.id, user_id=conn.user_id)
        connections.pop(conn.id, None)
        for s in list(conn.subjects):
            ids = subjects_index.get(s)
            if ids:
                ids.discard(conn.id)
                if not ids:
                    subjects_index.pop(s, None)
        asyncio.create_task(_presence_remove(conn))
        asyncio.create_task(_publish_connection_event("disconnected", conn))

@app.post("/internal/publish")
async def publish(payload: Dict[str, Any], request: Request):
    api_key = payload.get("api_key") or ""
    if GATEWAY_API_KEY and api_key != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")

    subjects = payload.get("subjects", [])
    message = payload.get("payload")
    traceparent = request.headers.get("traceparent", "")
    span_ctx = propagate.extract({"traceparent": traceparent}) if traceparent else None

    if tracing_enabled and _should_record(bool(traceparent)):
        with tracer.start_as_current_span("ws.publish.http", context=span_ctx, kind=SpanKind.SERVER) as span:
            span.set_attribute("ws.subjects_count", len(subjects))
            sent = await _send_to_subjects(subjects, message)
    else:
        sent = await _send_to_subjects(subjects, message)
    metrics["publish_total"] += 1
    return JSONResponse({"sent": sent})

@app.get("/metrics")
async def metrics_endpoint():
    lines = []
    for key, value in metrics.items():
        lines.append(f"{key} {value}")
    return PlainTextResponse("\n".join(lines) + "\n")

@app.get("/health")
async def health():
    return JSONResponse({"ok": True})

@app.get("/ready")
async def ready():
    return JSONResponse({"ok": True})

@app.get("/internal/connections")
async def list_connections(subject: Optional[str] = None, user_id: Optional[str] = None):
    results = []
    for conn in connections.values():
        if subject and subject not in conn.subjects:
            continue
        if user_id and user_id != conn.user_id:
            continue
        results.append({
            "connection_id": conn.id,
            "user_id": conn.user_id,
            "subjects": list(conn.subjects),
            "connected_at": conn.connected_at,
        })
    return JSONResponse({"connections": results})

@app.get("/internal/users/{user_id}/connections")
async def user_connections(user_id: str):
    results = []
    for conn in connections.values():
        if user_id != conn.user_id:
            continue
        results.append({
            "connection_id": conn.id,
            "user_id": conn.user_id,
            "subjects": list(conn.subjects),
            "connected_at": conn.connected_at,
        })
    return JSONResponse({"connections": results})
