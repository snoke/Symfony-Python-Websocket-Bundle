import asyncio
import json
import os
import time
import uuid
import hashlib
import hmac
from typing import Any, Dict, List, Optional, Set

import aio_pika
import httpx
import jwt
import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from jwt import PyJWKClient

app = FastAPI()

JWT_ALG = os.getenv("JWT_ALG", "RS256")
JWT_USER_ID_CLAIM = os.getenv("JWT_USER_ID_CLAIM", "user_id")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_PUBLIC_KEY_FILE = os.getenv("JWT_PUBLIC_KEY_FILE", "")
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "")
JWT_ISSUER = os.getenv("JWT_ISSUER", "")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "")
JWT_LEEWAY = int(os.getenv("JWT_LEEWAY", "0"))
SYMFONY_WEBHOOK_URL = os.getenv("SYMFONY_WEBHOOK_URL", "")
SYMFONY_WEBHOOK_SECRET = os.getenv("SYMFONY_WEBHOOK_SECRET", "")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
REDIS_DSN = os.getenv("REDIS_DSN", "")
REDIS_STREAM = os.getenv("REDIS_STREAM", "ws.outbox")
RABBITMQ_DSN = os.getenv("RABBITMQ_DSN", "")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "ws.outbox")
RABBITMQ_DLQ_QUEUE = os.getenv("RABBITMQ_DLQ_QUEUE", "ws.dlq")
REDIS_DLQ_STREAM = os.getenv("REDIS_DLQ_STREAM", "ws.dlq")
WEBHOOK_RETRY_ATTEMPTS = int(os.getenv("WEBHOOK_RETRY_ATTEMPTS", "3"))
WEBHOOK_RETRY_BASE_SECONDS = float(os.getenv("WEBHOOK_RETRY_BASE_SECONDS", "0.5"))
WS_RATE_LIMIT_PER_SEC = float(os.getenv("WS_RATE_LIMIT_PER_SEC", "10"))
WS_RATE_LIMIT_BURST = float(os.getenv("WS_RATE_LIMIT_BURST", "20"))

class Connection:
    def __init__(self, websocket: WebSocket, user_id: str, subjects: List[str]):
        self.id = str(uuid.uuid4())
        self.websocket = websocket
        self.user_id = user_id
        self.subjects = set(subjects)
        self.connected_at = int(time.time())
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

async def _post_webhook(event_type: str, conn: Connection, extra: Optional[Dict[str, Any]] = None) -> None:
    if not SYMFONY_WEBHOOK_URL:
        return
    payload = {
        "type": event_type,
        "connection_id": conn.id,
        "user_id": conn.user_id,
        "subjects": list(conn.subjects),
        "connected_at": conn.connected_at,
    }
    if extra:
        payload.update(extra)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    headers = {}
    if SYMFONY_WEBHOOK_SECRET:
        signature = hmac.new(
            SYMFONY_WEBHOOK_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    async with httpx.AsyncClient(timeout=5) as client:
        for attempt in range(WEBHOOK_RETRY_ATTEMPTS):
            try:
                await client.post(SYMFONY_WEBHOOK_URL, content=body, headers=headers)
                return
            except Exception:
                await asyncio.sleep(WEBHOOK_RETRY_BASE_SECONDS * (2 ** attempt))

async def _push_redis_dlq(client: redis.Redis, reason: str, raw: str) -> None:
    try:
        await client.xadd(REDIS_DLQ_STREAM, {"reason": reason, "raw": raw})
    except Exception:
        pass

async def _push_rabbit_dlq(channel: aio_pika.Channel, reason: str, raw: bytes) -> None:
    try:
        message = aio_pika.Message(body=raw, headers={"reason": reason})
        await channel.default_exchange.publish(message, routing_key=RABBITMQ_DLQ_QUEUE)
    except Exception:
        pass

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
                await channel.declare_queue(RABBITMQ_DLQ_QUEUE, durable=True)
                queue = await channel.declare_queue(RABBITMQ_QUEUE, durable=True)
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            try:
                                data = json.loads(message.body.decode("utf-8"))
                                subjects = data.get("subjects", [])
                                payload = data.get("payload")
                                await _send_to_subjects(subjects, payload)
                                backoff = 1.0
                            except Exception:
                                await _push_rabbit_dlq(channel, "parse_error", message.body)
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)

@app.on_event("startup")
async def startup_tasks() -> None:
    if REDIS_DSN:
        asyncio.create_task(_redis_outbox_consumer())
    if RABBITMQ_DSN:
        asyncio.create_task(_rabbit_outbox_consumer())

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

    asyncio.create_task(_post_webhook("connected", conn))

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
                continue
            asyncio.create_task(_post_webhook(
                "message_received",
                conn,
                {"message": data, "raw": msg}
            ))
    except WebSocketDisconnect:
        pass
    finally:
        connections.pop(conn.id, None)
        for s in list(conn.subjects):
            ids = subjects_index.get(s)
            if ids:
                ids.discard(conn.id)
                if not ids:
                    subjects_index.pop(s, None)
        asyncio.create_task(_post_webhook("disconnected", conn))

@app.post("/internal/publish")
async def publish(payload: Dict[str, Any]):
    api_key = payload.get("api_key") or ""
    if GATEWAY_API_KEY and api_key != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")

    subjects = payload.get("subjects", [])
    message = payload.get("payload")
    sent = await _send_to_subjects(subjects, message)
    return JSONResponse({"sent": sent})

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
