"""Two-tier cache: Redis when ``REDIS_URL`` is set, otherwise an in-process TTL cache.

Geocoding and routing results are expensive to fetch and highly repetitive (many customers
quote the same towns), so caching them is the single biggest provider-cost and latency win.
The in-process tier keeps development and single-instance deployments working without Redis;
it is per-process and therefore not shared, which is why ``cache_backend()`` is reported by
the readiness probe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger("app.cache")

_MISSING = object()


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    async def clear(self) -> None: ...
    def describe(self) -> str: ...


class MemoryCache:
    """Bounded LRU + TTL cache. Not shared between processes; adequate for one instance."""

    def __init__(self, max_entries: int = 5_000) -> None:
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + ttl_seconds, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    async def delete_prefix(self, prefix: str) -> None:
        async with self._lock:
            for key in [k for k in self._store if k.startswith(prefix)]:
                del self._store[key]

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            return {"entries": len(self._store), "max_entries": self._max_entries}

    def describe(self) -> str:
        return "memory"


class RedisCache:
    """Redis-backed cache with JSON serialisation."""

    def __init__(self, client: Any, prefix: str = "rims") -> None:
        self._client = client
        self._prefix = prefix

    def _full(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        import json

        raw = await self._client.get(self._full(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        import json

        await self._client.set(self._full(key), json.dumps(value, default=str), ex=ttl_seconds)

    async def delete_prefix(self, prefix: str) -> None:

        pattern = f"{self._prefix}:{prefix}*"
        keys = [k async for k in self._client.scan_iter(match=pattern, count=500)]
        if keys:
            await self._client.delete(*keys)

    async def clear(self) -> None:

        keys = [k async for k in self._client.scan_iter(match=f"{self._prefix}:*", count=500)]
        if keys:
            await self._client.delete(*keys)

    async def stats(self) -> dict[str, int]:
        info = await self._client.info()
        return {"entries": int(info.get("keyspace_hits", 0)), "max_entries": -1}

    def describe(self) -> str:
        return "redis"


_cache: Cache | None = None


async def get_cache() -> Cache:
    """Resolve the cache lazily. A Redis outage degrades to memory instead of failing requests."""
    global _cache
    if _cache is not None:
        return _cache
    settings = get_settings()
    if settings.redis_url:
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)
            await client.ping()
            _cache = RedisCache(client)
            logger.info("cache backend: redis")
            return _cache
        except Exception as exc:
            logger.warning("redis unavailable (%s); using in-process cache", type(exc).__name__)
    _cache = MemoryCache(max_entries=settings.cache_max_entries)
    logger.info("cache backend: memory")
    return _cache


def cache_backend_name() -> str:
    return _cache.describe() if _cache is not None else "uninitialised"


async def reset_cache() -> None:
    """Used by tests and by administrative cache invalidation."""
    global _cache
    if _cache is not None:
        await _cache.clear()
    _cache = None


async def cached(cache: Cache, key: str, ttl_seconds: int, factory: Any) -> Any:
    """Read-through cache. A factory failure propagates and is not cached."""
    value = await cache.get(key)
    if value is not _MISSING and value is not None:
        return value
    value = await factory()
    if value is not None:
        await cache.set(key, value, ttl_seconds)
    return value
