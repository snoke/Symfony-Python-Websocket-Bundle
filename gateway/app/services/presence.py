import json
import time
from typing import Optional

import redis.asyncio as redis

from .settings import Settings


class PresenceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.client: Optional[redis.Redis] = None

    async def startup(self) -> None:
        if self._settings.PRESENCE_REDIS_DSN:
            self.client = redis.from_url(self._settings.PRESENCE_REDIS_DSN, decode_responses=True)

    def effective_ttl(self) -> int:
        if self._settings.PRESENCE_STRATEGY == "session":
            return 0
        if self._settings.PRESENCE_STRATEGY == "heartbeat":
            return max(0, self._settings.PRESENCE_HEARTBEAT_SECONDS + self._settings.PRESENCE_GRACE_SECONDS)
        return max(0, self._settings.PRESENCE_TTL_SECONDS)

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
        await self.client.hset(conn_key, mapping=data)
        ttl = self.effective_ttl()
        if ttl > 0:
            await self.client.expire(conn_key, ttl)
        user_key = f"{prefix}user:{conn.user_id}"
        await self.client.sadd(user_key, conn.id)
        if ttl > 0:
            await self.client.expire(user_key, ttl)
        for subject in conn.subjects:
            subject_key = f"{prefix}subject:{subject}"
            await self.client.sadd(subject_key, conn.id)
            if ttl > 0:
                await self.client.expire(subject_key, ttl)

    async def refresh(self, conn) -> None:
        if not self.client:
            return
        ttl = self.effective_ttl()
        if ttl <= 0:
            return
        prefix = self._settings.PRESENCE_REDIS_PREFIX
        conn_key = f"{prefix}conn:{conn.id}"
        await self.client.hset(conn_key, mapping={"last_seen_at": str(int(time.time()))})
        await self.client.expire(conn_key, ttl)
        user_key = f"{prefix}user:{conn.user_id}"
        await self.client.expire(user_key, ttl)
        for subject in conn.subjects:
            await self.client.expire(f"{prefix}subject:{subject}", ttl)

    async def remove(self, conn) -> None:
        if not self.client:
            return
        prefix = self._settings.PRESENCE_REDIS_PREFIX
        await self.client.delete(f"{prefix}conn:{conn.id}")
        await self.client.srem(f"{prefix}user:{conn.user_id}", conn.id)
        for subject in conn.subjects:
            await self.client.srem(f"{prefix}subject:{subject}", conn.id)
