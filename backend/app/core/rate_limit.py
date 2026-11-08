"""
Fixed-window request rate limiting backed by Redis (shared across API replicas), with an
in-process fallback so a Redis outage degrades to per-process limits instead of none.
"""
import asyncio
import logging
import math
import time
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("radar.rate_limit")


class RateLimiter:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None
        self._local: dict[str, tuple[int, float]] = {}  # key -> (count, window_end)
        self._lock = asyncio.Lock()

    def _client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
        return self._redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Records one hit. Returns (allowed, retry_after_seconds)."""
        window = int(time.time() // window_seconds)
        redis_key = f"ratelimit:{key}:{window}"
        try:
            client = self._client()
            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds + 1)
            count, _ = await pipe.execute()
            retry_after = window_seconds - int(time.time() % window_seconds)
            return int(count) <= limit, max(retry_after, 1)
        except Exception as exc:
            logger.debug("Rate limiter falling back to in-memory: %s", exc)
            return await self._hit_local(key, limit, window_seconds)

    async def _hit_local(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        async with self._lock:
            count, window_end = self._local.get(key, (0, now + window_seconds))
            if now >= window_end:
                count, window_end = 0, now + window_seconds
            count += 1
            self._local[key] = (count, window_end)
            if len(self._local) > 50_000:  # bound memory under attack
                self._local = {k: v for k, v in self._local.items() if v[1] > now}
        return count <= limit, max(math.ceil(window_end - now), 1)

    def reset_local(self) -> None:
        self._local.clear()


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(key: str, limit: int, window_seconds: int, detail: str = "Too many requests.") -> None:
    allowed, retry_after = await rate_limiter.hit(key, limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{detail} Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
