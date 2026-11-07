"""Login attempt limiter.

Uses Redis when available. If Redis is unreachable it falls back to an in-process window
rather than failing open (no limit) or failing closed (owner locked out of the kill switch).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger

log = get_logger(__name__)


class LoginRateLimiter:
    def __init__(self, redis: Redis | None, max_attempts: int, window_seconds: int) -> None:
        self._redis = redis
        self._max = max_attempts
        self._window = window_seconds
        self._local: dict[str, deque[float]] = defaultdict(deque)

    def _local_hit(self, key: str, record: bool) -> int:
        now = time.monotonic()
        bucket = self._local[key]
        while bucket and bucket[0] <= now - self._window:
            bucket.popleft()
        if record:
            bucket.append(now)
        return len(bucket)

    async def _count(self, key: str, record: bool) -> int:
        if self._redis is not None:
            try:
                rkey = f"ratelimit:login:{key}"
                if record:
                    pipe = self._redis.pipeline()
                    pipe.incr(rkey)
                    pipe.expire(rkey, self._window, nx=True)
                    count, _ = await pipe.execute()
                    return int(count)
                value = await self._redis.get(rkey)
                return int(value or 0)
            except RedisError:
                log.warning("rate_limiter_redis_unavailable_using_local_fallback")
        return self._local_hit(key, record)

    async def is_blocked(self, *keys: str) -> bool:
        for key in keys:
            if await self._count(key, record=False) >= self._max:
                return True
        return False

    async def record_failure(self, *keys: str) -> None:
        for key in keys:
            await self._count(key, record=True)

    async def reset(self, *keys: str) -> None:
        for key in keys:
            self._local.pop(key, None)
            if self._redis is not None:
                try:
                    await self._redis.delete(f"ratelimit:login:{key}")
                except RedisError:
                    pass
