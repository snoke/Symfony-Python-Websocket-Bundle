import asyncio
import json
import time
from typing import Dict, Optional

import redis.asyncio as redis

from .settings import Settings


class PresenceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.client: Optional[redis.Redis] = None
        self._refresh_queue: Optional[asyncio.Queue] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._last_refresh: Dict[str, float] = {}

    async def startup(self) -> None:
        if self._settings.PRESENCE_REDIS_DSN:
            self.client = redis.from_url(self._settings.PRESENCE_REDIS_DSN, decode_responses=True)
        if self.client and self._refresh_queue is None:
            queue_size = max(1, self._settings.PRESENCE_REFRESH_QUEUE_SIZE)
            self._refresh_queue = asyncio.Queue(maxsize=queue_size)
            self._refresh_task = asyncio.create_task(self._refresh_worker())

    def effective_ttl(self) -> int:
        if self._settings.PRESENCE_STRATEGY == "session":
            return 0
        if self._settings.PRESENCE_STRATEGY == "heartbeat":
            return max(0, self._settings.PRESENCE_HEARTBEAT_SECONDS + self._settings.PRESENCE_GRACE_SECONDS)
        return max(0, self._settings.PRESENCE_TTL_SECONDS)

    def refresh(self, conn) -> None:
        if not self.client:
            return
        if not self._refresh_queue:
            asyncio.create_task(self._refresh_conn(conn))
            return
        try:
            self._refresh_queue.put_nowait(conn)
        except asyncio.QueueFull:
            asyncio.create_task(self._refresh_conn(conn))

    async def _refresh_worker(self) -> None:
        if not self._refresh_queue:
            return
        while True:
            conn = await self._refresh_queue.get()
            try:
                await self._refresh_conn(conn)
            finally:
                self._refresh_queue.task_done()

    def _should_refresh(self, conn, ttl: int) -> bool:
        if ttl <= 0:
            return False
        min_interval = max(0.0, float(self._settings.PRESENCE_REFRESH_MIN_INTERVAL_SECONDS))
        if min_interval <= 0:
            return True
        now = time.monotonic()
        last = self._last_refresh.get(conn.id, 0.0)
        if now - last < min_interval:
            return False
        self._last_refresh[conn.id] = now
        return True

    async def set(self, conn) -> None:
        if not self.client:
            return
        now = int(time.time())
        prefix = self._settings.PRESENCE_REDIS_PREFIX
        conn_key = f"{prefix}conn:{conn.id}"
        data = {
            "connection_id": conn.id,
            "user_id": conn.user_id,
            "subjects": json.dumps(list(conn.subjects)),
            "connected_at": str(conn.connected_at),
            "last_seen_at": str(now),
        }
        ttl = self.effective_ttl()
        user_key = f"{prefix}user:{conn.user_id}"
        pipe = self.client.pipeline(transaction=False)
        pipe.hset(conn_key, mapping=data)
        if ttl > 0:
            pipe.expire(conn_key, ttl)
        pipe.sadd(user_key, conn.id)
        if ttl > 0:
            pipe.expire(user_key, ttl)
        for subject in conn.subjects:
            subject_key = f"{prefix}subject:{subject}"
            pipe.sadd(subject_key, conn.id)
            if ttl > 0:
                pipe.expire(subject_key, ttl)
        await pipe.execute()

    async def _refresh_conn(self, conn) -> None:
        try:
            if not self.client:
                return
            ttl = self.effective_ttl()
            if not self._should_refresh(conn, ttl):
                return
            prefix = self._settings.PRESENCE_REDIS_PREFIX
            conn_key = f"{prefix}conn:{conn.id}"
            user_key = f"{prefix}user:{conn.user_id}"
            pipe = self.client.pipeline(transaction=False)
            pipe.hset(conn_key, mapping={"last_seen_at": str(int(time.time()))})
            pipe.expire(conn_key, ttl)
            pipe.expire(user_key, ttl)
            for subject in conn.subjects:
                pipe.expire(f"{prefix}subject:{subject}", ttl)
            await pipe.execute()
        except Exception:
            pass

    async def remove(self, conn) -> None:
        if not self.client:
            return
        prefix = self._settings.PRESENCE_REDIS_PREFIX
        pipe = self.client.pipeline(transaction=False)
        pipe.delete(f"{prefix}conn:{conn.id}")
        pipe.srem(f"{prefix}user:{conn.user_id}", conn.id)
        for subject in conn.subjects:
            pipe.srem(f"{prefix}subject:{subject}", conn.id)
        await pipe.execute()
        self._last_refresh.pop(conn.id, None)
