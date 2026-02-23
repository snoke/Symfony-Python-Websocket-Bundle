import asyncio
import json
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from fastapi import WebSocket

from .message import InternalMessage
from .settings import Settings


class Connection:
    def __init__(self, websocket: WebSocket, user_id: str, subjects: List[str], settings: Settings):
        self.id = str(uuid.uuid4())
        self.websocket = websocket
        self.user_id = user_id
        self.subjects = set(subjects)
        self.connected_at = int(time.time())
        self.traceparent = websocket.headers.get("traceparent", "")
        self._tokens = settings.WS_RATE_LIMIT_BURST
        self._last_refill = time.time()
        self._settings = settings
        self.buffer: Deque[Tuple[Dict[str, Any], str, InternalMessage]] = deque()
        self.buffer_event = asyncio.Event()
        self.buffer_task: Optional[asyncio.Task] = None
        self.outbox: Deque[str] = deque()
        self.outbox_event = asyncio.Event()
        self.outbox_task: Optional[asyncio.Task] = None
        self._outbox_lock = asyncio.Lock()
        self._closed = False

    def allow_message(self) -> bool:
        if self._settings.WS_RATE_LIMIT_PER_SEC <= 0:
            return True
        now = time.time()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(
            self._settings.WS_RATE_LIMIT_BURST,
            self._tokens + elapsed * self._settings.WS_RATE_LIMIT_PER_SEC,
        )
        self._last_refill = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    async def enqueue_outbox(self, text: str) -> bool:
        async with self._outbox_lock:
            if self._closed:
                return False
            if len(self.outbox) >= self._settings.WS_OUTBOX_QUEUE_SIZE:
                if self._settings.WS_OUTBOX_DROP_STRATEGY == "drop_oldest" and self.outbox:
                    self.outbox.popleft()
                else:
                    return False
            self.outbox.append(text)
            if not self.outbox_task or self.outbox_task.done():
                self.outbox_task = asyncio.create_task(self._drain_outbox())
            self.outbox_event.set()
        return True

    async def _drain_outbox(self) -> None:
        while True:
            await self.outbox_event.wait()
            while True:
                async with self._outbox_lock:
                    if not self.outbox:
                        self.outbox_event.clear()
                        if self._closed:
                            return
                        break
                    text = self.outbox.popleft()
                try:
                    await self.websocket.send_text(text)
                except Exception:
                    await self.close()
                    return

    async def close(self) -> None:
        async with self._outbox_lock:
            self._closed = True
            self.outbox.clear()
            self.outbox_event.set()


class ConnectionManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.connections: Dict[str, Connection] = {}
        self.subjects_index: Dict[str, Set[str]] = {}

    def add(self, websocket: WebSocket, user_id: str, subjects: List[str]) -> Connection:
        conn = Connection(websocket, user_id, subjects, self._settings)
        self.connections[conn.id] = conn
        for subject in conn.subjects:
            self.subjects_index.setdefault(subject, set()).add(conn.id)
        return conn

    async def remove(self, conn: Connection) -> None:
        self.connections.pop(conn.id, None)
        for subject in list(conn.subjects):
            ids = self.subjects_index.get(subject)
            if ids:
                ids.discard(conn.id)
                if not ids:
                    self.subjects_index.pop(subject, None)
        await conn.close()

    async def send_to_subjects(self, subjects: List[str], payload: Any) -> int:
        try:
            text = json.dumps({"type": "event", "payload": payload}, separators=(",", ":"), sort_keys=True)
        except Exception:
            return 0
        sent = 0
        target_ids: Set[str] = set()
        for subject in subjects:
            for cid in self.subjects_index.get(subject, set()):
                target_ids.add(cid)
        for cid in target_ids:
            conn = self.connections.get(cid)
            if conn is None:
                continue
            if await conn.enqueue_outbox(text):
                sent += 1
        return sent
