import asyncio
import json
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from fastapi import WebSocket

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
        self.buffer: Deque[Tuple[Dict[str, Any], str]] = deque()
        self.buffer_event = asyncio.Event()
        self.buffer_task: Optional[asyncio.Task] = None

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

    def remove(self, conn: Connection) -> None:
        self.connections.pop(conn.id, None)
        for subject in list(conn.subjects):
            ids = self.subjects_index.get(subject)
            if ids:
                ids.discard(conn.id)
                if not ids:
                    self.subjects_index.pop(subject, None)

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
            try:
                await conn.websocket.send_text(text)
                sent += 1
            except Exception:
                pass
        return sent
