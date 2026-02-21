import asyncio
import json
import os
import time
import uuid
import hashlib
import hmac
import logging
import random
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

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
RABBITMQ_QUEUE_TTL_MS = int(os.getenv("RABBITMQ_QUEUE_TTL_MS", "0"))
RABBITMQ_INBOX_EXCHANGE = os.getenv("RABBITMQ_INBOX_EXCHANGE", "ws.inbox")
RABBITMQ_INBOX_ROUTING_KEY = os.getenv("RABBITMQ_INBOX_ROUTING_KEY", "ws.inbox")
RABBITMQ_INBOX_QUEUE = os.getenv("RABBITMQ_INBOX_QUEUE", "")
RABBITMQ_INBOX_QUEUE_TTL_MS = int(os.getenv("RABBITMQ_INBOX_QUEUE_TTL_MS", "0"))
RABBITMQ_EVENTS_EXCHANGE = os.getenv("RABBITMQ_EVENTS_EXCHANGE", "ws.events")
RABBITMQ_EVENTS_ROUTING_KEY = os.getenv("RABBITMQ_EVENTS_ROUTING_KEY", "ws.events")
RABBITMQ_EVENTS_QUEUE = os.getenv("RABBITMQ_EVENTS_QUEUE", "")
RABBITMQ_EVENTS_QUEUE_TTL_MS = int(os.getenv("RABBITMQ_EVENTS_QUEUE_TTL_MS", "0"))
RABBITMQ_DLQ_QUEUE = os.getenv("RABBITMQ_DLQ_QUEUE", "ws.dlq")
RABBITMQ_DLQ_EXCHANGE = os.getenv("RABBITMQ_DLQ_EXCHANGE", "ws.dlq")
RABBITMQ_REPLAY_TARGET_EXCHANGE = os.getenv("RABBITMQ_REPLAY_TARGET_EXCHANGE", "")
RABBITMQ_REPLAY_TARGET_ROUTING_KEY = os.getenv("RABBITMQ_REPLAY_TARGET_ROUTING_KEY", "")
RABBITMQ_REPLAY_MAX_BATCH = int(os.getenv("RABBITMQ_REPLAY_MAX_BATCH", "100"))
REDIS_DLQ_STREAM = os.getenv("REDIS_DLQ_STREAM", "ws.dlq")
REDIS_INBOX_STREAM = os.getenv("REDIS_INBOX_STREAM", "ws.inbox")
REDIS_EVENTS_STREAM = os.getenv("REDIS_EVENTS_STREAM", "ws.events")
PRESENCE_REDIS_DSN = os.getenv("PRESENCE_REDIS_DSN", REDIS_DSN)
PRESENCE_REDIS_PREFIX = os.getenv("PRESENCE_REDIS_PREFIX", "presence:")
PRESENCE_TTL_SECONDS = int(os.getenv("PRESENCE_TTL_SECONDS", "120"))
PRESENCE_STRATEGY = os.getenv("PRESENCE_STRATEGY", "ttl").lower()
PRESENCE_HEARTBEAT_SECONDS = int(os.getenv("PRESENCE_HEARTBEAT_SECONDS", "30"))
PRESENCE_GRACE_SECONDS = int(os.getenv("PRESENCE_GRACE_SECONDS", "15"))
PRESENCE_REFRESH_ON_MESSAGE = os.getenv("PRESENCE_REFRESH_ON_MESSAGE", "1").lower() in ("1", "true", "yes")
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
REPLAY_STRATEGY = os.getenv("REPLAY_STRATEGY", "none").lower()
REPLAY_RETENTION_SECONDS = int(os.getenv("REPLAY_RETENTION_SECONDS", "0"))
REPLAY_MAXLEN = int(os.getenv("REPLAY_MAXLEN", "0"))
REPLAY_SNAPSHOT_SECONDS = int(os.getenv("REPLAY_SNAPSHOT_SECONDS", "0"))
REPLAY_API_KEY = os.getenv("REPLAY_API_KEY", "")
REPLAY_RATE_LIMIT_STRATEGY = os.getenv("REPLAY_RATE_LIMIT_STRATEGY", "in_memory").lower()
REPLAY_RATE_LIMIT_PER_MINUTE = int(os.getenv("REPLAY_RATE_LIMIT_PER_MINUTE", "10"))
REPLAY_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("REPLAY_RATE_LIMIT_WINDOW_SECONDS", "60"))
REPLAY_RATE_LIMIT_REDIS_DSN = os.getenv("REPLAY_RATE_LIMIT_REDIS_DSN", REDIS_DSN)
REPLAY_RATE_LIMIT_PREFIX = os.getenv("REPLAY_RATE_LIMIT_PREFIX", "replay:rate:")
REPLAY_RATE_LIMIT_KEY = os.getenv("REPLAY_RATE_LIMIT_KEY", "api_key_or_ip").lower()
REPLAY_IDEMPOTENCY_STRATEGY = os.getenv("REPLAY_IDEMPOTENCY_STRATEGY", "none").lower()
REPLAY_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("REPLAY_IDEMPOTENCY_TTL_SECONDS", "900"))
REPLAY_IDEMPOTENCY_REDIS_DSN = os.getenv("REPLAY_IDEMPOTENCY_REDIS_DSN", REPLAY_RATE_LIMIT_REDIS_DSN)
REPLAY_IDEMPOTENCY_PREFIX = os.getenv("REPLAY_IDEMPOTENCY_PREFIX", "replay:idempotency:")
REPLAY_IDEMPOTENCY_HEADER = os.getenv("REPLAY_IDEMPOTENCY_HEADER", "Idempotency-Key")
REPLAY_IDEMPOTENCY_PAYLOAD_FIELD = os.getenv("REPLAY_IDEMPOTENCY_PAYLOAD_FIELD", "idempotency_key")
REPLAY_AUDIT_LOG = os.getenv("REPLAY_AUDIT_LOG", "1").lower() in ("1", "true", "yes", "on")
WS_RATE_LIMIT_PER_SEC = float(os.getenv("WS_RATE_LIMIT_PER_SEC", "10"))
WS_RATE_LIMIT_BURST = float(os.getenv("WS_RATE_LIMIT_BURST", "20"))
ORDERING_STRATEGY = os.getenv("ORDERING_STRATEGY", "none").lower()
ORDERING_TOPIC_FIELD = os.getenv("ORDERING_TOPIC_FIELD", "topic")
ORDERING_SUBJECT_SOURCE = os.getenv("ORDERING_SUBJECT_SOURCE", "user").lower()
ORDERING_PARTITION_MODE = os.getenv("ORDERING_PARTITION_MODE", "none").lower()
ORDERING_PARTITION_MAX_LEN = int(os.getenv("ORDERING_PARTITION_MAX_LEN", "64"))
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
if REPLAY_STRATEGY not in ("none", "bounded", "durable"):
    REPLAY_STRATEGY = "none"
if REPLAY_RETENTION_SECONDS < 0:
    REPLAY_RETENTION_SECONDS = 0
if REPLAY_MAXLEN < 0:
    REPLAY_MAXLEN = 0
if REPLAY_SNAPSHOT_SECONDS < 0:
    REPLAY_SNAPSHOT_SECONDS = 0
if REPLAY_RATE_LIMIT_PER_MINUTE < 0:
    REPLAY_RATE_LIMIT_PER_MINUTE = 0
if REPLAY_RATE_LIMIT_WINDOW_SECONDS <= 0:
    REPLAY_RATE_LIMIT_WINDOW_SECONDS = 60
if REPLAY_RATE_LIMIT_STRATEGY not in ("in_memory", "redis", "none"):
    REPLAY_RATE_LIMIT_STRATEGY = "in_memory"
if REPLAY_RATE_LIMIT_KEY not in ("api_key", "ip", "api_key_or_ip", "api_key_and_ip"):
    REPLAY_RATE_LIMIT_KEY = "api_key_or_ip"
if REPLAY_IDEMPOTENCY_STRATEGY not in ("none", "in_memory", "redis"):
    REPLAY_IDEMPOTENCY_STRATEGY = "none"
if REPLAY_IDEMPOTENCY_TTL_SECONDS < 0:
    REPLAY_IDEMPOTENCY_TTL_SECONDS = 0
if ORDERING_STRATEGY not in ("none", "topic", "subject"):
    ORDERING_STRATEGY = "none"
if ORDERING_SUBJECT_SOURCE not in ("user", "subject"):
    ORDERING_SUBJECT_SOURCE = "user"
if ORDERING_PARTITION_MODE not in ("none", "suffix"):
    ORDERING_PARTITION_MODE = "none"
if PRESENCE_STRATEGY not in ("ttl", "heartbeat", "session"):
    PRESENCE_STRATEGY = "ttl"
if PRESENCE_HEARTBEAT_SECONDS < 0:
    PRESENCE_HEARTBEAT_SECONDS = 0
if PRESENCE_GRACE_SECONDS < 0:
    PRESENCE_GRACE_SECONDS = 0

logger = logging.getLogger("gateway")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logger.level)
logger.addHandler(handler)

_ORDERING_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._:-]")

metrics: Dict[str, int] = {
    "ws_connections_total": 0,
    "ws_disconnects_total": 0,
    "ws_messages_total": 0,
    "ws_rate_limited_total": 0,
    "publish_total": 0,
    "broker_publish_total": 0,
    "webhook_publish_total": 0,
    "webhook_publish_failed_total": 0,
    "rabbitmq_replay_total": 0,
    "replay_api_requests_total": 0,
    "replay_api_denied_total": 0,
    "replay_api_rate_limited_total": 0,
    "replay_api_idempotent_total": 0,
    "replay_api_success_total": 0,
    "replay_api_errors_total": 0,
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
_last_stream_trim: Dict[str, float] = {}

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

def _audit(event: str, **fields: Any) -> None:
    if REPLAY_AUDIT_LOG:
        _log(event, **fields)

def _normalize_key(value: str) -> str:
    value = value.strip()
    if len(value) <= 128:
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _rate_limit_identity(api_key: str, caller_ip: str) -> str:
    if REPLAY_RATE_LIMIT_KEY == "api_key":
        return api_key or caller_ip
    if REPLAY_RATE_LIMIT_KEY == "ip":
        return caller_ip
    if REPLAY_RATE_LIMIT_KEY == "api_key_and_ip":
        if api_key:
            return f"{api_key}:{caller_ip}"
        return caller_ip
    return api_key or caller_ip

class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        now = time.time()
        cutoff = now - window_seconds
        async with self._lock:
            bucket = self._buckets.get(key, [])
            bucket = [ts for ts in bucket if ts >= cutoff]
            if len(bucket) >= limit:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True

class RedisRateLimiter:
    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        window = int(time.time() // window_seconds)
        redis_key = f"{self._prefix}{key}:{window}"
        count = await self._client.incr(redis_key)
        if count == 1:
            await self._client.expire(redis_key, window_seconds)
        return count <= limit

class NullIdempotencyStore:
    async def get(self, key: str) -> Optional[int]:
        return None

    async def set(self, key: str, value: int, ttl_seconds: int) -> None:
        return None

class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._items: Dict[str, Tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[int]:
        now = time.time()
        async with self._lock:
            if key not in self._items:
                return None
            value, expires_at = self._items[key]
            if expires_at and now > expires_at:
                self._items.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: int, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0.0
        async with self._lock:
            self._items[key] = (value, expires_at)

class RedisIdempotencyStore:
    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    async def get(self, key: str) -> Optional[int]:
        value = await self._client.get(f"{self._prefix}{key}")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: int, ttl_seconds: int) -> None:
        redis_key = f"{self._prefix}{key}"
        if ttl_seconds > 0:
            await self._client.setex(redis_key, ttl_seconds, str(value))
        else:
            await self._client.set(redis_key, str(value))

def _build_rate_limiter() -> InMemoryRateLimiter | RedisRateLimiter:
    if REPLAY_RATE_LIMIT_STRATEGY == "redis" and REPLAY_RATE_LIMIT_REDIS_DSN:
        client = redis.from_url(REPLAY_RATE_LIMIT_REDIS_DSN, decode_responses=True)
        return RedisRateLimiter(client, REPLAY_RATE_LIMIT_PREFIX)
    return InMemoryRateLimiter()

def _build_idempotency_store() -> NullIdempotencyStore | InMemoryIdempotencyStore | RedisIdempotencyStore:
    if REPLAY_IDEMPOTENCY_STRATEGY == "redis" and REPLAY_IDEMPOTENCY_REDIS_DSN:
        client = redis.from_url(REPLAY_IDEMPOTENCY_REDIS_DSN, decode_responses=True)
        return RedisIdempotencyStore(client, REPLAY_IDEMPOTENCY_PREFIX)
    if REPLAY_IDEMPOTENCY_STRATEGY == "in_memory":
        return InMemoryIdempotencyStore()
    return NullIdempotencyStore()

replay_rate_limiter = _build_rate_limiter()
replay_idempotency_store = _build_idempotency_store()
def _normalize_ordering_key(raw_key: str) -> str:
    key = (raw_key or "").strip()
    if not key:
        return ""
    raw_bytes = key.encode("utf-8")
    if ORDERING_PARTITION_MAX_LEN > 0 and len(key) > ORDERING_PARTITION_MAX_LEN:
        key = hashlib.sha1(raw_bytes).hexdigest()
    key = _ORDERING_KEY_SAFE_RE.sub("_", key)
    if not key:
        key = hashlib.sha1(raw_bytes).hexdigest()
    return key

def _derive_ordering_key(conn: "Connection", data: Optional[Dict[str, Any]]) -> str:
    if ORDERING_STRATEGY == "none":
        return ""
    if ORDERING_STRATEGY == "topic":
        if not data:
            return ""
        key = data.get(ORDERING_TOPIC_FIELD)
        if key is None and isinstance(data.get("meta"), dict):
            key = data["meta"].get(ORDERING_TOPIC_FIELD)
        if key is None:
            key = data.get("type")
        return str(key) if key else ""
    if ORDERING_STRATEGY == "subject":
        key = None
        if data:
            if isinstance(data.get("subject"), str):
                key = data.get("subject")
            elif isinstance(data.get("subjects"), list) and data.get("subjects"):
                key = data.get("subjects")[0]
        if not key:
            if ORDERING_SUBJECT_SOURCE == "subject" and conn.subjects:
                key = sorted(conn.subjects)[0]
            else:
                key = conn.user_id
        return str(key) if key else ""
    return ""

def _apply_ordering_partition(stream: Optional[str], routing_key: str, ordering_key: str) -> tuple[Optional[str], str]:
    if ORDERING_PARTITION_MODE != "suffix" or not ordering_key:
        return stream, routing_key
    safe_key = _normalize_ordering_key(ordering_key)
    if not safe_key:
        return stream, routing_key
    if stream:
        stream = f"{stream}.{safe_key}"
    routing_key = f"{routing_key}.{safe_key}"
    return stream, routing_key

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

def _rabbit_queue_args(ttl_ms: int) -> Dict[str, Any]:
    args: Dict[str, Any] = {}
    if ttl_ms > 0:
        args["x-message-ttl"] = ttl_ms
    if RABBITMQ_DLQ_EXCHANGE:
        args["x-dead-letter-exchange"] = RABBITMQ_DLQ_EXCHANGE
        if RABBITMQ_DLQ_QUEUE:
            args["x-dead-letter-routing-key"] = RABBITMQ_DLQ_QUEUE
    return args

async def _maybe_trim_stream(client: redis.Redis, stream: str) -> None:
    if REPLAY_STRATEGY != "bounded":
        return
    if REPLAY_RETENTION_SECONDS <= 0:
        return
    now = time.time()
    last = _last_stream_trim.get(stream, 0.0)
    interval = max(1.0, min(60.0, REPLAY_RETENTION_SECONDS / 4))
    if now - last < interval:
        return
    min_id = f"{int((now - REPLAY_RETENTION_SECONDS) * 1000)}-0"
    try:
        await client.xtrim(stream, minid=min_id)
    except Exception:
        pass
    _last_stream_trim[stream] = now

async def _publish_broker(stream: Optional[str], exchange: Optional[aio_pika.Exchange], routing_key: str, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if redis_publish_client and stream:
        try:
            kwargs: Dict[str, Any] = {}
            if REPLAY_STRATEGY == "bounded" and REPLAY_MAXLEN > 0:
                kwargs["maxlen"] = REPLAY_MAXLEN
                kwargs["approximate"] = True
            await redis_publish_client.xadd(stream, {"data": body}, **kwargs)
            metrics["broker_publish_total"] += 1
            await _maybe_trim_stream(redis_publish_client, stream)
        except Exception:
            pass
    if exchange:
        try:
            message = aio_pika.Message(body=body.encode("utf-8"))
            await exchange.publish(message, routing_key=routing_key)
            metrics["broker_publish_total"] += 1
        except Exception:
            pass

async def _publish_event(
    event_type: str,
    stream: Optional[str],
    exchange: Optional[aio_pika.Exchange],
    routing_key: str,
    payload: Dict[str, Any],
    ordering_key: str = "",
) -> None:
    stream, routing_key = _apply_ordering_partition(stream, routing_key, ordering_key)
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
    ordering_key = _derive_ordering_key(conn, data)
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
    if ordering_key:
        payload["ordering_key"] = ordering_key
        payload["ordering_strategy"] = ORDERING_STRATEGY

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
                ordering_key=ordering_key,
            )
    else:
        await _publish_event(
            "message_received",
            REDIS_INBOX_STREAM,
            rabbit_inbox_exchange,
            RABBITMQ_INBOX_ROUTING_KEY,
            payload,
            ordering_key=ordering_key,
        )

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

def _presence_effective_ttl() -> int:
    if PRESENCE_STRATEGY == "session":
        return 0
    if PRESENCE_STRATEGY == "heartbeat":
        return max(0, PRESENCE_HEARTBEAT_SECONDS + PRESENCE_GRACE_SECONDS)
    return max(0, PRESENCE_TTL_SECONDS)

async def _presence_set(conn: Connection) -> None:
    if not presence_client:
        return
    now = int(time.time())
    prefix = PRESENCE_REDIS_PREFIX
    conn_key = f"{prefix}conn:{conn.id}"
    data = {
        "connection_id": conn.id,
        "user_id": conn.user_id,
        "subjects": json.dumps(list(conn.subjects)),
        "connected_at": str(conn.connected_at),
        "last_seen_at": str(now),
    }
    await presence_client.hset(conn_key, mapping=data)
    ttl = _presence_effective_ttl()
    if ttl > 0:
        await presence_client.expire(conn_key, ttl)
    user_key = f"{prefix}user:{conn.user_id}"
    await presence_client.sadd(user_key, conn.id)
    if ttl > 0:
        await presence_client.expire(user_key, ttl)
    for subject in conn.subjects:
        subject_key = f"{prefix}subject:{subject}"
        await presence_client.sadd(subject_key, conn.id)
        if ttl > 0:
            await presence_client.expire(subject_key, ttl)

async def _presence_refresh(conn: Connection) -> None:
    if not presence_client:
        return
    ttl = _presence_effective_ttl()
    if ttl <= 0:
        return
    prefix = PRESENCE_REDIS_PREFIX
    conn_key = f"{prefix}conn:{conn.id}"
    await presence_client.hset(conn_key, mapping={"last_seen_at": str(int(time.time()))})
    await presence_client.expire(conn_key, ttl)
    user_key = f"{prefix}user:{conn.user_id}"
    await presence_client.expire(user_key, ttl)
    for subject in conn.subjects:
        await presence_client.expire(f"{prefix}subject:{subject}", ttl)

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
                queue = await channel.declare_queue(
                    RABBITMQ_QUEUE,
                    durable=True,
                    arguments=_rabbit_queue_args(RABBITMQ_QUEUE_TTL_MS),
                )
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
        if RABBITMQ_DLQ_EXCHANGE and RABBITMQ_DLQ_QUEUE:
            dlq_exchange = await rabbit_publish_channel.declare_exchange(
                RABBITMQ_DLQ_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True,
            )
            dlq_queue = await rabbit_publish_channel.declare_queue(RABBITMQ_DLQ_QUEUE, durable=True)
            await dlq_queue.bind(dlq_exchange, routing_key=RABBITMQ_DLQ_QUEUE)
        if RABBITMQ_INBOX_QUEUE and rabbit_inbox_exchange:
            inbox_queue = await rabbit_publish_channel.declare_queue(
                RABBITMQ_INBOX_QUEUE,
                durable=True,
                arguments=_rabbit_queue_args(RABBITMQ_INBOX_QUEUE_TTL_MS),
            )
            await inbox_queue.bind(rabbit_inbox_exchange, routing_key=RABBITMQ_INBOX_ROUTING_KEY)
        if RABBITMQ_EVENTS_QUEUE and rabbit_events_exchange:
            events_queue = await rabbit_publish_channel.declare_queue(
                RABBITMQ_EVENTS_QUEUE,
                durable=True,
                arguments=_rabbit_queue_args(RABBITMQ_EVENTS_QUEUE_TTL_MS),
            )
            await events_queue.bind(rabbit_events_exchange, routing_key=RABBITMQ_EVENTS_ROUTING_KEY)
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
            msg_type = data.get("type")
            if msg_type in ("ping", "heartbeat"):
                if PRESENCE_STRATEGY in ("ttl", "heartbeat"):
                    if msg_type == "heartbeat" or PRESENCE_REFRESH_ON_MESSAGE:
                        asyncio.create_task(_presence_refresh(conn))
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.send_json({"type": "heartbeat_ack"})
                continue
            if not conn.allow_message():
                await websocket.send_json({"type": "rate_limited"})
                metrics["ws_rate_limited_total"] += 1
                _log("ws_rate_limited", connection_id=conn.id, user_id=conn.user_id)
                continue
            metrics["ws_messages_total"] += 1
            if PRESENCE_STRATEGY in ("ttl", "heartbeat") and PRESENCE_REFRESH_ON_MESSAGE:
                asyncio.create_task(_presence_refresh(conn))
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

@app.post("/internal/replay/rabbitmq")
async def replay_rabbitmq(payload: Dict[str, Any], request: Request):
    metrics["replay_api_requests_total"] += 1
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    caller_ip = request.client.host if request.client else "unknown"
    api_key = payload.get("api_key") or request.headers.get("X-API-Key") or request.headers.get("X-Api-Key") or ""
    expected_key = REPLAY_API_KEY or GATEWAY_API_KEY

    if expected_key and api_key != expected_key:
        metrics["replay_api_denied_total"] += 1
        _audit("replay_api_denied", request_id=request_id, caller_ip=caller_ip)
        raise HTTPException(status_code=401, detail="invalid api key")
    if not RABBITMQ_DSN:
        metrics["replay_api_errors_total"] += 1
        _audit("replay_api_error", request_id=request_id, caller_ip=caller_ip, error="rabbitmq not configured")
        raise HTTPException(status_code=500, detail="rabbitmq not configured")

    identity = _normalize_key(_rate_limit_identity(api_key, caller_ip) or caller_ip)
    if REPLAY_RATE_LIMIT_STRATEGY != "none" and REPLAY_RATE_LIMIT_PER_MINUTE > 0:
        allowed = await replay_rate_limiter.allow(identity, REPLAY_RATE_LIMIT_PER_MINUTE, REPLAY_RATE_LIMIT_WINDOW_SECONDS)
        if not allowed:
            metrics["replay_api_rate_limited_total"] += 1
            _audit("replay_api_rate_limited", request_id=request_id, caller_ip=caller_ip, identity=identity)
            raise HTTPException(status_code=429, detail="rate limit exceeded")

    idempotency_key = request.headers.get(REPLAY_IDEMPOTENCY_HEADER, "") or payload.get(REPLAY_IDEMPOTENCY_PAYLOAD_FIELD, "")
    idempotency_key = _normalize_key(idempotency_key) if idempotency_key else ""
    if idempotency_key:
        cached = await replay_idempotency_store.get(idempotency_key)
        if cached is not None:
            metrics["replay_api_idempotent_total"] += 1
            _audit("replay_api_idempotent", request_id=request_id, caller_ip=caller_ip, replayed=cached)
            return JSONResponse({"replayed": cached, "idempotent": True})

    limit = int(payload.get("limit") or RABBITMQ_REPLAY_MAX_BATCH)
    if limit <= 0:
        return JSONResponse({"replayed": 0})
    limit = min(limit, RABBITMQ_REPLAY_MAX_BATCH)

    target_exchange = RABBITMQ_REPLAY_TARGET_EXCHANGE or RABBITMQ_INBOX_EXCHANGE
    target_routing_key = RABBITMQ_REPLAY_TARGET_ROUTING_KEY or RABBITMQ_INBOX_ROUTING_KEY

    replayed = 0
    try:
        connection = await aio_pika.connect_robust(RABBITMQ_DSN)
        async with connection:
            channel = await connection.channel()
            dlq_exchange = await channel.declare_exchange(RABBITMQ_DLQ_EXCHANGE, ExchangeType.DIRECT, durable=True)
            dlq_queue = await channel.declare_queue(RABBITMQ_DLQ_QUEUE, durable=True)
            await dlq_queue.bind(dlq_exchange, routing_key=RABBITMQ_DLQ_QUEUE)

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
        metrics["replay_api_errors_total"] += 1
        _audit("replay_api_error", request_id=request_id, caller_ip=caller_ip, error=str(exc))
        raise HTTPException(status_code=500, detail="replay failed") from exc

    if idempotency_key:
        await replay_idempotency_store.set(idempotency_key, replayed, REPLAY_IDEMPOTENCY_TTL_SECONDS)

    metrics["rabbitmq_replay_total"] += replayed
    metrics["replay_api_success_total"] += 1
    _audit("replay_api_success", request_id=request_id, caller_ip=caller_ip, replayed=replayed, limit=limit)
    return JSONResponse({"replayed": replayed})

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
