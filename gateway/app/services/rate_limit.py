import asyncio
import time
from typing import Dict, Optional, Tuple

import redis.asyncio as redis

from .settings import Settings


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, list[float]] = {}
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


def build_rate_limiter(settings: Settings) -> InMemoryRateLimiter | RedisRateLimiter:
    if settings.REPLAY_RATE_LIMIT_STRATEGY == "redis" and settings.REPLAY_RATE_LIMIT_REDIS_DSN:
        client = redis.from_url(settings.REPLAY_RATE_LIMIT_REDIS_DSN, decode_responses=True)
        return RedisRateLimiter(client, settings.REPLAY_RATE_LIMIT_PREFIX)
    return InMemoryRateLimiter()


def build_idempotency_store(settings: Settings) -> NullIdempotencyStore | InMemoryIdempotencyStore | RedisIdempotencyStore:
    if settings.REPLAY_IDEMPOTENCY_STRATEGY == "redis" and settings.REPLAY_IDEMPOTENCY_REDIS_DSN:
        client = redis.from_url(settings.REPLAY_IDEMPOTENCY_REDIS_DSN, decode_responses=True)
        return RedisIdempotencyStore(client, settings.REPLAY_IDEMPOTENCY_PREFIX)
    if settings.REPLAY_IDEMPOTENCY_STRATEGY == "in_memory":
        return InMemoryIdempotencyStore()
    return NullIdempotencyStore()
