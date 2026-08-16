"""Redis client wrapper.

Provides a class-based Redis client for connection management and operations.
"""

import json
from typing import Any, TypeVar

from redis import asyncio as aioredis

from app.core.config import settings

JsonValue = TypeVar("JsonValue")


class RedisClient:
    """Redis client wrapper for connection lifecycle management.

    Usage in FastAPI lifespan:
        async with contextmanager():
            redis = RedisClient(settings.REDIS_URL)
            await redis.connect()
            yield {"redis": redis}
            await redis.close()
    """

    def __init__(self, url: str | None = None):
        self.url = url or settings.REDIS_URL
        self.client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis server."""
        self.client = aioredis.from_url(  # type: ignore[no-untyped-call]
            self.url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self.client = None

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.get(key)  # type: ignore[no-any-return]

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
    ) -> None:
        """Set a value with optional TTL (in seconds)."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        await self.client.set(key, value, ex=ttl)

    async def get_json(self, key: str) -> Any | None:
        """Get and decode a JSON value by key.

        Returns ``None`` when the key does not exist. Invalid JSON is allowed to
        raise ``json.JSONDecodeError`` so callers can detect corrupted cache data.
        """
        value = await self.get(key)
        return None if value is None else json.loads(value)

    async def set_json(
        self,
        key: str,
        value: JsonValue,
        ttl: int | None = None,
    ) -> None:
        """Serialize and store a JSON-compatible value with optional TTL."""
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl=ttl)

    async def delete(self, key: str) -> int:
        """Delete a key. Returns number of keys deleted."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.delete(key)  # type: ignore[no-any-return]

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.exists(key))

    async def expire(self, key: str, ttl: int) -> bool:
        """Set a key's expiration time in seconds."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.expire(key, ttl))

    async def ttl(self, key: str) -> int:
        """Return remaining TTL in seconds, following Redis TTL semantics."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.ttl(key)  # type: ignore[no-any-return]

    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment an integer value and return the updated value."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.incrby(key, amount)  # type: ignore[no-any-return]

    async def ping(self) -> bool:
        """Ping Redis server. Returns True if connected."""
        if not self.client:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            return False

    @property
    def raw(self) -> aioredis.Redis:
        """Access the underlying aioredis client for advanced operations."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return self.client
