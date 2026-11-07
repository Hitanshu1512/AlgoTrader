"""Real-time event fan-out to dashboard WebSockets via Redis pub/sub.

This is *notification* plumbing only. Durable trading events (intents, orders) use Redis
Streams with consumer groups from Phase 4. Nothing here is a source of truth.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import get_logger, redact

CHANNEL = "algotrader:events"
log = get_logger(__name__)


class EventBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        message = {"topic": topic, "ts": datetime.now(UTC).isoformat(), "data": redact(data)}
        try:
            await self._redis.publish(CHANNEL, json.dumps(message, default=str))
        except RedisError:
            log.warning("event_publish_failed", topic=topic)
